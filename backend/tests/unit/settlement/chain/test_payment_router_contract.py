"""SC-5 / SC-6 / SC-9 — `PaymentRouter.sol` is the commit-point lock, tested against a real EVM.

Canonical: `docs/contracts/settlement-contract-freeze.md` §1 (SC-5, SC-6, SC-9, SC-11)
Reference: `.pi/architecture/modules/settlement.md#components` (scenario 6, the bypass path)

`contracts/test/PaymentRouter.t.sol` would need `forge`, which is not installed here. These tests are
its replacement with the same meaning: the Solidity is compiled by solc 0.8.24 (`foundry.toml`'s pinned
version and `evm_version = paris`) and executed on `eth-tester`'s py-evm backend, so the assertions are
about the deployed bytecode — storage, events, named errors, EIP-712 recovery — not about a mock.

Each test is one rule the module cannot lose:

* a payment moves USDC once and spends the nullifier (SC-5, SC-9);
* a replay reverts with the *named* error `NullifierSpent`, and moves nothing (SC-6, scenario 6);
* a signature that does not recover to the owner reverts `OwnerSignatureInvalid` and moves nothing
  (A-15, S-2);
* the `Anchored` event carries the order id and nullifier, so the app can bind a receipt to an order;
* `spentNullifiers` flips to true — the read that lets the app refuse one layer earlier (SC-5).
"""

from __future__ import annotations

import pytest
from src.settlement.infrastructure.chain.abi import ROUTER_ABI
from web3.logs import DISCARD

from tests.unit.settlement.chain._evm import (
    SOLC_VERSION,
    LocalChain,
    compiled_contracts,
    decode_revert_name,
    deploy_local_chain,
)

ORDER_ID = "0b9a1b3c4d5e6f708192a3b4c5d6e7f8"
NULLIFIER = "0x" + "ab" * 32
AMOUNT = 42_500_000  # 42.50 USDC in micro-units (SC-9: integer micro-units, never floats)


@pytest.fixture
def chain() -> LocalChain:
    """A fresh chain with `PaymentRouter` and `TestUsdc` deployed (see `_evm.py`)."""
    return deploy_local_chain()


def _pay(chain: LocalChain, *, nullifier: bytes = bytes.fromhex("ab" * 32), amount: int = AMOUNT):
    """Build the router's `pay` call for the operator as payer, with the order's frozen facts."""
    return chain.router.functions.pay(
        chain.order_ref(ORDER_ID),
        nullifier,
        chain.payee,
        amount,
        False,
        b"",
    )


class TestCompiledContract:
    def test_the_adapter_abi_is_the_compiler_abi(self) -> None:
        """ADR-007: the Python adapter and the contract must not keep two hand-written field lists.

        The gateway embeds `ROUTER_ABI` (no forge, no checked-in build artifact), so this test is what
        makes that safe: recompile and compare. Renaming, reordering or adding a function/error/event
        fails here until both sides move in one commit.
        """
        compiled = compiled_contracts()

        assert compiled.version == SOLC_VERSION
        assert compiled.abi["PaymentRouter"] == ROUTER_ABI

    def test_the_router_is_deployed_for_this_chain_and_this_token(self, chain: LocalChain) -> None:
        """SC-11: the token and the owner are constructor arguments, never module constants."""
        assert chain.router.functions.usdc().call() == chain.usdc.address
        assert chain.router.functions.owner().call() == chain.owner


class TestPayment:
    def test_a_payment_moves_usdc_and_spends_the_nullifier(self, chain: LocalChain) -> None:
        """SC-5 / SC-9: the payee receives exactly the frozen amount, once."""
        before = chain.usdc.functions.balanceOf(chain.payee).call()

        receipt = chain.wait(chain.send(_pay(chain)))

        assert receipt.status == 1
        assert chain.usdc.functions.balanceOf(chain.payee).call() - before == AMOUNT
        assert chain.router.functions.spentNullifiers(bytes.fromhex("ab" * 32)).call() is True

    def test_the_payment_emits_anchored_with_the_order_and_nullifier(
        self, chain: LocalChain
    ) -> None:
        """The `Anchored` event is how a receipt is bound to an order — ids only, never routing data."""
        receipt = chain.wait(chain.send(_pay(chain)))

        logs = [
            log
            for log in chain.router.events.Anchored().process_receipt(receipt, errors=DISCARD)
            if log["address"] == chain.router.address
        ]

        assert len(logs) == 1
        args = logs[0]["args"]
        assert bytes(args["orderId"]) == chain.order_ref(ORDER_ID)
        assert bytes(args["nullifier"]) == bytes.fromhex("ab" * 32)
        # `txRef` names the exact movement (order, nullifier, payer, payee, amount) — not a second id.
        assert len(bytes(args["txRef"])) == 32

    def test_a_replayed_nullifier_reverts_with_the_named_error(self, chain: LocalChain) -> None:
        """SC-6 / scenario 6: even with the app bypassed, the contract refuses the second payment."""
        chain.wait(chain.send(_pay(chain)))
        paid = chain.usdc.functions.balanceOf(chain.payee).call()

        with pytest.raises(Exception) as raised:  # a revert, in whatever shape the provider reports
            chain.call(_pay(chain))

        assert decode_revert_name(raised.value) == "NullifierSpent"
        assert chain.usdc.functions.balanceOf(chain.payee).call() == paid

    def test_a_zero_amount_is_refused_before_the_nullifier_is_spent(
        self, chain: LocalChain
    ) -> None:
        """SC-9: a payment that moves nothing must not consume the invoice's marker."""
        with pytest.raises(Exception) as raised:
            chain.call(_pay(chain, amount=0))

        assert decode_revert_name(raised.value) == "AmountNotPositive"
        assert chain.router.functions.spentNullifiers(bytes.fromhex("ab" * 32)).call() is False


class TestOwnerSignature:
    def test_an_owner_signed_payment_is_accepted(self, chain: LocalChain) -> None:
        """A-15: the owner's EIP-712 signature over these exact bytes is what the contract wants."""
        order_ref = chain.order_ref(ORDER_ID)
        nullifier = bytes.fromhex("cd" * 32)
        signature = chain.sign_payment(
            chain.owner_key,
            order_ref=order_ref,
            nullifier=nullifier,
            payee=chain.payee,
            amount=AMOUNT,
        )

        receipt = chain.wait(
            chain.send(
                chain.router.functions.pay(
                    order_ref, nullifier, chain.payee, AMOUNT, True, signature
                )
            )
        )

        assert receipt.status == 1
        assert chain.usdc.functions.balanceOf(chain.payee).call() == AMOUNT

    def test_a_bad_owner_signature_reverts_and_moves_nothing(self, chain: LocalChain) -> None:
        """A-15: the operator's own key is not the owner's — a stolen operator key cannot pay."""
        order_ref = chain.order_ref(ORDER_ID)
        nullifier = bytes.fromhex("cd" * 32)
        signature = chain.sign_payment(
            chain.operator_key,  # signed by the payer, not the owner
            order_ref=order_ref,
            nullifier=nullifier,
            payee=chain.payee,
            amount=AMOUNT,
        )

        with pytest.raises(Exception) as raised:
            chain.call(
                chain.router.functions.pay(
                    order_ref, nullifier, chain.payee, AMOUNT, True, signature
                )
            )

        assert decode_revert_name(raised.value) == "OwnerSignatureInvalid"
        assert chain.usdc.functions.balanceOf(chain.payee).call() == 0
        assert chain.router.functions.spentNullifiers(nullifier).call() is False

    def test_a_missing_owner_signature_reverts(self, chain: LocalChain) -> None:
        """The flag is not advisory: no signature bytes is `OwnerSignatureRequired`, not a fallback."""
        with pytest.raises(Exception) as raised:
            chain.call(
                chain.router.functions.pay(
                    chain.order_ref(ORDER_ID),
                    bytes.fromhex("cd" * 32),
                    chain.payee,
                    AMOUNT,
                    True,
                    b"",
                )
            )

        assert decode_revert_name(raised.value) == "OwnerSignatureRequired"

    def test_an_owner_signature_for_another_payer_cannot_be_replayed(
        self, chain: LocalChain
    ) -> None:
        """A-15: `payer` is inside the signed struct, so one operator cannot spend another's allowance."""
        order_ref = chain.order_ref(ORDER_ID)
        nullifier = bytes.fromhex("ef" * 32)
        # The owner signs for `operator`, but the call is made by the *owner* account as payer.
        signature = chain.sign_payment(
            chain.owner_key,
            order_ref=order_ref,
            nullifier=nullifier,
            payee=chain.payee,
            amount=AMOUNT,
            payer=chain.operator,
        )

        with pytest.raises(Exception) as raised:
            chain.router.functions.pay(
                order_ref, nullifier, chain.payee, AMOUNT, True, signature
            ).call({"from": chain.owner})

        assert decode_revert_name(raised.value) == "OwnerSignatureInvalid"


class TestAnchor:
    def test_an_anchor_write_emits_anchored_without_moving_funds(self, chain: LocalChain) -> None:
        """ADR-006: anchoring is a timestamp for a hash, never a settlement — it spends no nullifier."""
        anchored = b"\x5a" * 32

        receipt = chain.wait(chain.send(chain.router.functions.anchor(anchored)))

        assert receipt.status == 1
        assert chain.usdc.functions.balanceOf(chain.payee).call() == 0
        assert chain.router.functions.spentNullifiers(anchored).call() is False
        logs = chain.router.events.Anchored().process_receipt(receipt, errors=DISCARD)
        assert len(logs) == 1
        assert bytes(logs[0]["args"]["txRef"]) == anchored
        # No order context on an anchor: `bytes32(0)` for both indexed fields.
        assert bytes(logs[0]["args"]["orderId"]) == b"\x00" * 32
        assert bytes(logs[0]["args"]["nullifier"]) == b"\x00" * 32
