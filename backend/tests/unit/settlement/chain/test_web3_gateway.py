"""SC-3 / SC-6 / SC-7 / SC-10 — `Web3ChainGateway` against a real EVM, in two phases.

Canonical: `docs/contracts/settlement-contract-freeze.md` §1 and §7 (the two-phase port)
Reference: `.pi/architecture/modules/settlement.md#ports-infrastructure-adapters`

The suite drives the adapter end to end: `prepare` signs a `PaymentRouter.pay` locally and moves nothing,
`broadcast` sends those exact bytes, the transaction mines, `receipt` reads it back with gas and
confirmations, and `is_nullifier_spent` reads the on-chain marker. Nothing is mocked — the provider is an
in-process `eth-tester` chain, which is the injection point the constructor exists for (no anvil, no
network, no fork).

What each test defends:

* **SC-3** — the hash exists before anything is broadcast (`prepare`), an order that already has a hash is
  never signed again, and re-sending the persisted bytes is one transaction, not a second payment;
* **SC-6** — a refusal is a `SettlementRefusal` naming the contract's error, and a bypassed replay reads
  back from the chain as `REVERTED` rather than as an unexplained zero;
* **SC-7** — confirmations are measured from the chain and compared against the stricter of the network
  and the settings, never assumed;
* **SC-9 / SC-10** — the amount moved is the order's frozen amount, and the receipt carries gas/fee.
"""

from __future__ import annotations

import pytest
from eth_account import Account
from src.settlement.domain.chain_receipt import ChainReceipt
from src.settlement.domain.errors import SecondTransactionRefused, SettlementRefusal, UnknownNetwork
from src.settlement.domain.ids import OrderId
from src.settlement.domain.ports import SignedPayment
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import ChainNetwork, ReceiptStatus
from src.settlement.infrastructure.chain.web3_gateway import Web3ChainGateway
from src.shared.domain.errors import RefusalError, ValidationError
from src.shared.infrastructure.config import Settings, load_settings
from web3.logs import DISCARD

from tests.unit.settlement._fixtures import a_determination, an_intent
from tests.unit.settlement.chain._evm import LocalChain

PAYEE_ADDRESS = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
AMOUNT_MICRO_USDC = 42_500_000  # 42.50 USDC — taken from `an_intent()`, never passed to `prepare`


def an_order(network: ChainNetwork, **intent_overrides: object) -> SettlementOrder:
    """An `ORDERED` order bound to `network`, built through the aggregate's only entry point (SC-1)."""
    intent = an_intent(**intent_overrides)
    return SettlementOrder.order(intent, network, a_determination(intent_id=intent.intent_id))


async def a_signed_order(
    chain: LocalChain, gateway: Web3ChainGateway, network: ChainNetwork, **intent_overrides: object
) -> tuple[SettlementOrder, SignedPayment]:
    """A `SIGNED` order: signed locally, hash persisted on it, nothing broadcast.

    This is the state the write path persists (SC-3), built here through the aggregate's own transition
    rather than by assigning fields — the test would otherwise prove a state the aggregate cannot enter.
    """
    order = an_order(network, **intent_overrides)
    signed = await gateway.prepare(order)
    order.mark_signed(signed.tx_hash, signed.raw_transaction, order.amount)
    return order, signed


class TestPrepare:
    async def test_prepare_returns_a_hash_and_moves_nothing(
        self, chain: LocalChain, gateway: Web3ChainGateway, chain_network: ChainNetwork
    ) -> None:
        """SC-3: the hash is known before broadcast — that is the whole reason the port is two-phase."""
        order = an_order(chain_network)
        blocks = chain.w3.eth.block_number
        nonce = chain.w3.eth.get_transaction_count(chain.operator, "pending")

        signed = await gateway.prepare(order)

        # The hash and the bytes it identifies, both local facts, both available with nothing sent.
        assert len(signed.tx_hash) == 66 and signed.tx_hash.startswith("0x")
        assert signed.raw_transaction.startswith("0x")
        assert chain.w3.eth.get_transaction_count(chain.operator, "pending") == nonce
        # Nothing moved: no balance, no block, no spent nullifier.
        assert chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call() == 0
        assert chain.w3.eth.block_number == blocks
        assert await gateway.is_nullifier_spent(order.nullifier) is False
        # The order itself was not mutated by signing: the aggregate owns that transition.
        assert order.tx_hash is None
        assert order.status.value == "ordered"
        with pytest.raises(Exception):  # noqa: B017 - "no receipt" is the point; the type is the node's
            chain.w3.eth.get_transaction_receipt(bytes.fromhex(signed.tx_hash[2:]))

    async def test_prepare_twice_on_the_same_order_is_refused(
        self, chain: LocalChain, gateway: Web3ChainGateway, chain_network: ChainNetwork
    ) -> None:
        """SC-3: a second signature is a second nonce and a second payment. Refuse, keep the hash."""
        order, signed = await a_signed_order(chain, gateway, chain_network)
        blocks = chain.w3.eth.block_number
        balance = chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call()

        with pytest.raises(SecondTransactionRefused) as raised:
            await gateway.prepare(order)

        assert raised.value.details["existing_tx_hash"] == signed.tx_hash
        assert chain.w3.eth.block_number == blocks
        assert chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call() == balance
        assert order.tx_hash == signed.tx_hash

    async def test_an_order_requiring_the_owner_signature_is_refused_and_never_broadcast(
        self, chain: LocalChain, gateway: Web3ChainGateway, chain_network: ChainNetwork
    ) -> None:
        """A-15: the settlement key cannot stand in for the owner — the lock is never downgraded."""
        order = an_order(chain_network, requires_owner_signature=True)
        blocks = chain.w3.eth.block_number
        nonce = chain.w3.eth.get_transaction_count(chain.operator, "pending")

        with pytest.raises(SettlementRefusal) as raised:
            await gateway.prepare(order)

        assert raised.value.details["reason"] == "owner_signature_required"
        assert isinstance(raised.value, RefusalError)
        # Nothing was signed, so broadcast has nothing to attempt: the refusal is the end of the path.
        assert order.tx_hash is None
        assert chain.w3.eth.get_transaction_count(chain.operator, "pending") == nonce
        assert chain.w3.eth.block_number == blocks
        assert chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call() == 0

    async def test_a_node_rejection_is_a_refusal_not_a_traceback(
        self, chain: LocalChain, chain_network: ChainNetwork
    ) -> None:
        """SC-6: an unfunded signer is a documented refusal (409), not a 500 from a provider trace."""
        unfunded = Account.create().key.hex()
        settings = load_settings(
            settlement_private_key=unfunded,
            payment_router_address=chain.router.address,
            usdc_address=chain.usdc.address,
            chain_id=chain.w3.eth.chain_id,
            confirmations_required=1,
        )
        gateway = Web3ChainGateway(chain.w3, chain_network, settings)
        order = an_order(chain_network)

        with pytest.raises(SettlementRefusal) as raised:
            await gateway.prepare(order)

        assert raised.value.details["stage"] == "prepare"
        assert chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call() == 0

    async def test_prepare_refuses_a_spent_nullifier_before_broadcasting(
        self, chain: LocalChain, gateway: Web3ChainGateway, chain_network: ChainNetwork
    ) -> None:
        """SC-6 / scenario 6: the node rejects the replay at estimation, so nothing is signed or sent."""
        first, first_signed = await a_signed_order(chain, gateway, chain_network)
        await gateway.broadcast(first_signed)
        # Same invoice identity in the same household → the same nullifier, a different order id.
        replay = an_order(chain_network)
        assert replay.nullifier == first.nullifier
        assert replay.id != first.id

        with pytest.raises(SettlementRefusal) as raised:
            await gateway.prepare(replay)

        # The named error is decoded from the revert, not guessed from a message.
        assert raised.value.details["reason"] == "NullifierSpent"
        assert chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call() == AMOUNT_MICRO_USDC


class TestBroadcast:
    async def test_broadcast_moves_the_usdc_and_produces_a_receipt_with_the_anchored_event(
        self, chain: LocalChain, gateway: Web3ChainGateway, chain_network: ChainNetwork
    ) -> None:
        """The port's whole point: the bytes that were signed are the payment that lands."""
        order, signed = await a_signed_order(chain, gateway, chain_network)
        assert chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call() == 0

        await gateway.broadcast(signed)

        receipt = await gateway.receipt(signed.tx_hash, order_id=order.id)
        assert receipt is not None
        assert receipt.status is ReceiptStatus.SUCCESS
        assert receipt.order_id == order.id
        assert receipt.tx_hash == signed.tx_hash
        # SC-10: a receipt without cost is not a receipt.
        assert receipt.gas_used > 0
        assert int(receipt.gas_price) > 0
        # SC-9: exactly the frozen intent amount moved, and only to the intent's payee.
        assert chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call() == AMOUNT_MICRO_USDC
        # The signer is the key from settings, not a node-held account.
        assert chain.w3.eth.get_transaction(signed.tx_hash)["from"] == chain.operator
        # The `Anchored` event is the chain's own record of which order was paid.
        mined = chain.wait(bytes.fromhex(signed.tx_hash[2:]))
        logs = [
            log
            for log in chain.router.events.Anchored().process_receipt(mined, errors=DISCARD)
            if log["address"] == chain.router.address
        ]
        assert len(logs) == 1
        args = logs[0]["args"]
        assert bytes(args["orderId"]).hex() == Web3ChainGateway.order_ref(order.id).hex()
        assert bytes(args["nullifier"]).hex() == order.nullifier.value[2:]
        # `txRef` is keccak of the movement itself — non-zero for a payment, zero for an anchor.
        assert bytes(args["txRef"]).hex().strip("0")

    async def test_broadcast_flips_the_on_chain_nullifier(
        self, chain: LocalChain, gateway: Web3ChainGateway, chain_network: ChainNetwork
    ) -> None:
        """SC-5 from the chain side: `spentNullifiers` is how the app refuses a replay first."""
        order, signed = await a_signed_order(chain, gateway, chain_network)
        assert await gateway.is_nullifier_spent(order.nullifier) is False

        await gateway.broadcast(signed)

        assert await gateway.is_nullifier_spent(order.nullifier) is True

    async def test_broadcasting_the_persisted_bytes_again_cannot_pay_twice(
        self, chain: LocalChain, gateway: Web3ChainGateway, chain_network: ChainNetwork
    ) -> None:
        """SC-3/SC-5: recovery is a replay of one transaction, never a second payment.

        The node may accept the repeat (same hash, same nonce) or refuse it as already known; either
        answer is fine. What must hold is that the payee is paid once.
        """
        order, signed = await a_signed_order(chain, gateway, chain_network)
        await gateway.broadcast(signed)

        try:
            await gateway.broadcast(signed)
        except SettlementRefusal as refused:
            assert refused.details["stage"] == "broadcast"

        assert chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call() == AMOUNT_MICRO_USDC
        receipt = await gateway.receipt(signed.tx_hash, order_id=order.id)
        assert receipt is not None
        assert receipt.status is ReceiptStatus.SUCCESS

    async def test_broadcast_refuses_bytes_that_do_not_hash_to_the_recorded_hash(
        self, chain: LocalChain, gateway: Web3ChainGateway, chain_network: ChainNetwork
    ) -> None:
        """A hash and its bytes are one fact: mismatched, the order would point at a pollable nothing."""
        _, signed = await a_signed_order(chain, gateway, chain_network)
        wrong = SignedPayment(tx_hash="0x" + "ab" * 32, raw_transaction=signed.raw_transaction)

        with pytest.raises(SettlementRefusal) as raised:
            await gateway.broadcast(wrong)

        assert raised.value.details["reason"] == "tx_hash_mismatch"
        # Refused before the node saw it: nothing was mined and nothing moved.
        assert chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call() == 0


class TestReceipt:
    async def test_a_bypassed_replay_reads_back_as_a_refusal(
        self, chain: LocalChain, gateway: Web3ChainGateway, chain_network: ChainNetwork
    ) -> None:
        """SC-6: even a transaction the app never sent is reported as a refusal, with its reason.

        This is the scenario-6 bypass: an attacker with the operator's key sends the call directly. The
        gateway did not sign it, and must still be able to read the outcome and the contract's error.
        """
        first, signed = await a_signed_order(chain, gateway, chain_network)
        await gateway.broadcast(signed)
        replay = an_order(chain_network)
        bypassed = chain.wait(
            chain.send(
                chain.router.functions.pay(
                    Web3ChainGateway.order_ref(replay.id),
                    bytes.fromhex(replay.nullifier.value[2:]),
                    PAYEE_ADDRESS,
                    replay.amount.micro_usdc,
                    False,
                    b"",
                )
            )
        )

        receipt = await gateway.receipt(
            "0x" + bytes(bypassed.transactionHash).hex(), order_id=replay.id
        )

        assert receipt is not None
        assert receipt.status is ReceiptStatus.REVERTED
        assert receipt.revert_reason == "NullifierSpent"
        assert receipt.confirmed is False
        assert chain.usdc.functions.balanceOf(PAYEE_ADDRESS).call() == AMOUNT_MICRO_USDC
        assert first.tx_hash == signed.tx_hash

    async def test_receipt_is_none_while_the_transaction_is_unknown(
        self, gateway: Web3ChainGateway
    ) -> None:
        """The port returns `None` for "not mined yet" — it never invents a receipt or a hash."""
        assert await gateway.receipt("0x" + "00" * 32) is None

    async def test_confirmations_are_measured_and_finality_uses_the_stricter_policy(
        self, chain: LocalChain, chain_network: ChainNetwork
    ) -> None:
        """SC-7: the depth is a chain fact; the threshold is `max(network, settings)`."""
        settings = load_settings(
            settlement_private_key=chain.operator_key.hex(),
            payment_router_address=chain.router.address,
            usdc_address=chain.usdc.address,
            chain_id=chain.w3.eth.chain_id,
            confirmations_required=2,  # stricter than the network's 1, and never weaker
        )
        gateway = Web3ChainGateway(chain.w3, chain_network, settings)
        assert gateway.confirmations_required == 2

        order, signed = await a_signed_order(chain, gateway, chain_network)
        await gateway.broadcast(signed)
        shallow = await gateway.receipt(signed.tx_hash, order_id=order.id)
        assert shallow is not None
        assert shallow.confirmations == 1
        assert gateway.is_final(shallow) is False

        chain.tester.mine_blocks(1)
        deep = await gateway.receipt(signed.tx_hash, order_id=order.id)
        assert deep is not None
        assert deep.confirmations == 2
        assert gateway.is_final(deep) is True

    async def test_a_receipt_without_a_named_order_uses_the_on_chain_reference(
        self, chain: LocalChain, gateway: Web3ChainGateway, chain_network: ChainNetwork
    ) -> None:
        """The `Anchored` event is the chain's own order reference — readable without a lookup table."""
        order, signed = await a_signed_order(chain, gateway, chain_network)
        await gateway.broadcast(signed)

        receipt = await gateway.receipt(signed.tx_hash)

        assert isinstance(receipt, ChainReceipt)
        assert receipt.order_id == OrderId("0x" + Web3ChainGateway.order_ref(order.id).hex())
        assert receipt.is_anchor is False


class TestAnchor:
    async def test_an_anchor_write_is_readable_and_never_a_settlement(
        self, chain: LocalChain, gateway: Web3ChainGateway
    ) -> None:
        """ADR-006: an anchor timestamps a hash; it spends no nullifier and names no order."""
        anchored = "0x" + "5a" * 32

        tx_hash = await gateway.anchor(anchored)
        receipt = await gateway.receipt(tx_hash)
        mined = chain.wait(bytes.fromhex(tx_hash[2:]))

        assert receipt is not None
        assert receipt.status is ReceiptStatus.SUCCESS
        assert receipt.is_anchor is True
        assert receipt.order_id == OrderId("0x" + "00" * 32)
        assert mined.status == 1
        logs = [
            log
            for log in chain.router.events.Anchored().process_receipt(mined, errors=DISCARD)
            if log["address"] == chain.router.address
        ]
        assert len(logs) == 1
        assert bytes(logs[0]["args"]["txRef"]).hex() == anchored[2:]

    async def test_a_malformed_anchor_hash_is_a_validation_refusal(
        self, gateway: Web3ChainGateway
    ) -> None:
        """A malformed reference is 422 data, refused before a transaction is signed."""
        with pytest.raises(ValidationError):
            await gateway.anchor("0xdeadbeef")


class TestConfiguration:
    def test_a_network_from_another_chain_is_refused(
        self, chain: LocalChain, chain_settings: Settings
    ) -> None:
        """SC-11: signing for a chain this adapter was not configured for is the address leak."""
        with pytest.raises(UnknownNetwork):
            Web3ChainGateway(chain.w3, ChainNetwork.anvil(), chain_settings)

    def test_a_gateway_without_a_settlement_key_is_refused(self, chain: LocalChain) -> None:
        """An adapter that exists is an adapter that can sign — otherwise it must not be built."""
        settings = load_settings(settlement_private_key="")

        with pytest.raises(SettlementRefusal) as raised:
            Web3ChainGateway(
                chain.w3,
                ChainNetwork(
                    chain_id=chain.w3.eth.chain_id,
                    router_address=chain.router.address,
                    usdc_address=chain.usdc.address,
                    confirmations_required=1,
                ),
                settings,
            )

        assert raised.value.details["setting"] == "BURSAR_SETTLEMENT_PRIVATE_KEY"


def test_no_settlement_key_means_no_gateway_and_no_lie() -> None:
    """A deployment that cannot sign must report the absence, not a gateway that refuses at use."""
    from src.settlement.interfaces.http.router import _build_chain_gateway
    from src.shared.infrastructure.config import Settings

    settings = Settings(settlement_private_key="")  # type: ignore[call-arg]
    assert _build_chain_gateway(settings) is None


def test_an_unreachable_node_is_a_named_absence_not_a_boot_failure() -> None:
    """A configured key plus no node must not crash the app: the gateway needs the connected chain id
    to refuse signing across a chain boundary (SC-11), so construction is deferred until the node is
    reachable. The absence is logged and reported, never faked."""
    from src.settlement.interfaces.http.router import _build_chain_gateway
    from src.shared.infrastructure.config import Settings

    settings = Settings(  # type: ignore[call-arg]
        settlement_private_key="0x" + "11" * 32,
        payment_router_address="0x" + "22" * 20,
        usdc_address="0x" + "33" * 20,
        chain_id=31337,
        rpc_url="http://127.0.0.1:1",  # nothing listens here
    )
    assert _build_chain_gateway(settings) is None


def test_the_install_hook_injects_the_built_gateway(monkeypatch) -> None:
    """The deployable's hook is what makes `on-chain nullifier read` real; it must set the state the
    dispatch service reads, and it must let an injected gateway win (tests and demos inject fakes)."""
    from src.settlement.interfaces.http import router as http_module

    sentinel = object()
    monkeypatch.setattr(http_module, "_build_chain_gateway", lambda settings: sentinel)
    app = _FakeApp(settings=object())
    app.state.session_factory = object()
    monkeypatch.setattr(http_module, "build_services", lambda *a, **k: object())
    http_module.install(app)
    for hook in app.state.startup_hooks:
        hook(app)
    assert app.state.settlement_chain_gateway is sentinel


class _FakeApp:
    """The minimum an install hook touches: a router registry and `state`."""

    class _State:
        def __init__(self, **kw):
            self.startup_hooks = []
            self.settlement_services = None
            for k, v in kw.items():
                setattr(self, k, v)

    def __init__(self, **kw):
        self.state = self._State(**kw)
        self.routers = []

    def include_router(self, router):
        self.routers.append(router)
