"""`Web3ChainGateway` — the `ChainGateway` port against a real EVM.

Canonical: `.pi/architecture/modules/settlement.md#ports-infrastructure-adapters`
Reference: `docs/contracts/settlement-contract-freeze.md` §2.8 (`ChainGateway`), §1 (SC-3, SC-6,
SC-7, SC-9, SC-10, SC-11)

What this adapter is responsible for, and what it deliberately is not:

* **`submit(order)` signs once.** The order is the only input: the calldata is built from
  `order.payee_address`, `order.amount` and `order.nullifier`, never from a parameter a caller could
  taint (SC-2, SC-9). An order that already carries a `tx_hash` is refused with
  `SecondTransactionRefused` *before* a nonce is taken: re-signing a submitted order is a second
  payment, which is the one thing SC-3 exists to make impossible.
* **`receipt(tx_hash)` reports chain facts only.** Status, block, confirmations, gas, gas price and a
  fee estimate — the fields `ChainReceipt` refuses to be incomplete without (SC-10). Finality is *not*
  decided here: `is_final` compares the measured depth against `confirmations_required`, and the
  aggregate still owns the `PENDING`/`CONFIRMED` decision (SC-7).
* **`is_nullifier_spent`** reads `PaymentRouter.spentNullifiers` — the on-chain copy of SC-5.
* **A refusal, never a traceback.** Every provider failure (node rejects the tx, RPC dies, the token
  transfer reverts) becomes a `SettlementRefusal` with the contract's *named* error decoded from the
  revert data, so the API layer answers 409 with a reason instead of 500 (SC-6, SC-12's spirit).

Two things are configured, not hardcoded: the token and router addresses come from `ChainNetwork`
(SC-11 — Anvil and Base Sepolia must never share an address), and the signer comes from
`settings.settlement_private_key` (operator-held, never in an agent workspace).

The confirmation depth is `max(network.confirmations_required, settings.confirmations_required)`. The
network value is the contract's (SC-7/SC-11); the setting may raise the bar for an operator who wants
more depth than the module pins, and can never lower it — a config mistake must not make a settlement
final earlier than the module says.
"""

from __future__ import annotations

import ast
import asyncio
import re
from typing import TYPE_CHECKING, Any, Final

from eth_account import Account
from eth_typing import ChecksumAddress
from eth_utils import keccak, to_checksum_address
from hexbytes import HexBytes
from web3 import Web3
from web3.exceptions import TransactionNotFound
from web3.types import Wei

from src.settlement.domain.chain_receipt import ChainReceipt
from src.settlement.domain.errors import (
    SecondTransactionRefused,
    SettlementRefusal,
    UnknownNetwork,
)
from src.settlement.domain.ids import OrderId, ReceiptId, new_id
from src.settlement.domain.ports import ChainGateway
from src.settlement.domain.values import ChainNetwork, Nullifier, ReceiptStatus
from src.settlement.infrastructure.chain.abi import ROUTER_ABI, ROUTER_ERROR_SELECTORS
from src.shared.domain.errors import ErrorCode, ValidationError
from src.shared.domain.money import Money

if TYPE_CHECKING:
    from src.settlement.domain.settlement_order import SettlementOrder
    from src.shared.infrastructure.config import Settings

__all__ = [
    "DEFAULT_WEI_PER_MICRO_USDC",
    "Web3ChainGateway",
    "named_contract_error",
    "revert_payload",
]

#: Demo accounting rate for the receipt's fee estimate: 1 ETH = 1 USDC, so 1 micro-USDC = 1e12 wei.
#: A production adapter takes the rate from an oracle instead; the number is injected, not assumed, and
#: `ChainReceipt.fee_usdc_estimate` stays an estimate either way (ADR-006 — never a competing balance).
DEFAULT_WEI_PER_MICRO_USDC: Final[int] = 1_000_000_000_000

#: The router's only event: `Anchored(bytes32 indexed, bytes32 indexed, bytes32)`.
_ANCHORED_TOPIC: Final[str] = "0x" + keccak(text="Anchored(bytes32,bytes32,bytes32)").hex()

#: `bytes32(0)` — the order reference an anchor write (or an unattributed revert) carries.
_NO_ORDER_REF: Final[str] = "0x" + "00" * 32

#: eth-tester reports revert data as a `bytes` repr instead of `0x`-hex; a real node uses hex.
_BYTES_REPR: Final[re.Pattern[str]] = re.compile(r"b'(?:\\.|[^'\\])*'")


class Web3ChainGateway(ChainGateway):
    """`ChainGateway` over web3: one signature per order, receipts with cost, nullifier reads."""

    def __init__(
        self,
        provider: Web3,
        network: ChainNetwork,
        settings: Settings,
        *,
        abi: list[dict[str, Any]] | None = None,
        wei_per_micro_usdc: int = DEFAULT_WEI_PER_MICRO_USDC,
        gas_headroom_percent: int = 20,
    ) -> None:
        """Bind a provider, a network and an operator key.

        The provider is injected rather than built from a URL so a test can pass an in-process
        `EthereumTesterProvider` and exercise the same code path a node would (no anvil, no network).

        Raises:
            SettlementRefusal: no settlement key is configured, or the key is not a valid secp256k1
                key. An adapter that exists is an adapter that can sign.
            UnknownNetwork: the connected chain is not the network this adapter was configured for —
                signing across that boundary is the address leak SC-11 names.
        """
        key = settings.settlement_private_key.get_secret_value()
        if not key:
            raise SettlementRefusal(
                ErrorCode.CONFLICT,
                "No settlement key is configured, so nothing can be signed.",
                details={"setting": "BURSAR_SETTLEMENT_PRIVATE_KEY"},
            )
        try:
            self._account = Account.from_key(key)
        except (ValueError, TypeError) as exc:
            raise SettlementRefusal(
                ErrorCode.CONFLICT,
                "The configured settlement key is not a valid secp256k1 private key.",
                details={"setting": "BURSAR_SETTLEMENT_PRIVATE_KEY"},
            ) from exc

        connected_chain_id: int = provider.eth.chain_id
        if connected_chain_id != network.chain_id:
            # Never sign for a chain we were not configured for: the router/USDC pair would be another
            # network's, and the funds would move on the wrong chain (SC-11).
            raise UnknownNetwork(connected_chain_id)

        if wei_per_micro_usdc <= 0:
            raise ValidationError(
                "the fee conversion rate must be positive",
                wei_per_micro_usdc=str(wei_per_micro_usdc),
            )
        if gas_headroom_percent < 0:
            raise ValidationError(
                "gas headroom cannot be negative", percent=str(gas_headroom_percent)
            )

        self._w3 = provider
        self._network = network
        self._router = provider.eth.contract(
            address=to_checksum_address(network.router_address), abi=abi or ROUTER_ABI
        )
        self._wei_per_micro_usdc = wei_per_micro_usdc
        self._gas_headroom_percent = gas_headroom_percent
        self._confirmations_required = max(
            network.confirmations_required, settings.confirmations_required
        )

    # ── reads ───────────────────────────────────────────────────────────────

    @property
    def payer(self) -> ChecksumAddress:
        """The operator account that pays gas and holds the USDC allowance (derived from the key)."""
        return to_checksum_address(self._account.address)

    @property
    def confirmations_required(self) -> int:
        """The depth a receipt must reach to be final: the stricter of network and settings (SC-7)."""
        return self._confirmations_required

    def is_final(self, receipt: ChainReceipt) -> bool:
        """True when this receipt is successful and deep enough for *this* deploy's policy (SC-7)."""
        return receipt.is_final(self._confirmations_required)

    async def is_nullifier_spent(self, nullifier: Nullifier) -> bool:
        """Read `PaymentRouter.spentNullifiers` (SC-5, SC-6).

        A read failure is a refusal, not a `False`: reporting "unspent" because the node was down is
        exactly how a duplicate payment gets a second chance.
        """
        try:
            return bool(await asyncio.to_thread(self._spent_sync, nullifier))
        except SettlementRefusal:
            # A refusal is already the right answer; wrapping it would blur the reason.
            raise
        except Exception as exc:  # provider boundary: every failure is a refusal
            raise self._refusal(exc, stage="nullifier_read") from exc

    async def receipt(
        self, tx_hash: str, *, order_id: OrderId | None = None
    ) -> ChainReceipt | None:
        """Read the receipt for a hash, or `None` while it is not mined (SC-7, SC-10).

        `order_id` is optional so the port's one-argument signature still holds. Without it the receipt
        is attributed to the `Anchored` event's on-chain order reference; a caller that will conclude an
        order always names it, because a receipt for another order can never conclude this one (SC-4).
        """
        try:
            return await asyncio.to_thread(self._receipt_sync, tx_hash, order_id)
        except SettlementRefusal:
            raise
        except Exception as exc:  # provider boundary: every failure is a refusal
            raise self._refusal(exc, stage="receipt_read") from exc

    # ── writes ──────────────────────────────────────────────────────────────

    async def submit(self, order: SettlementOrder) -> str:
        """Sign and broadcast `PaymentRouter.pay` for this order; return the tx hash (SC-3, SC-9).

        Raises:
            SecondTransactionRefused: the order already carries a tx hash. Re-signing would take a new
                nonce and could pay twice (SC-3); the caller re-polls the existing hash instead.
            SettlementRefusal: the order needs the owner's EIP-712 signature, which the settlement key
                cannot produce — the second lock is never silently downgraded (A-15).
            SettlementRefusal: the node refused the transaction (nothing was broadcast).
        """
        if order.tx_hash is not None:
            raise SecondTransactionRefused(order_id=str(order.id), existing_tx_hash=order.tx_hash)
        if order.requires_owner_signature:
            # The router verifies an EIP-712 signature from the immutable owner. The order carries the
            # fact that one is required but no signature bytes, so the only honest answer is a refusal:
            # sending an empty signature would make the contract revert, and dropping the flag would
            # disarm the lock the order asked for.
            raise SettlementRefusal(
                ErrorCode.CONFLICT,
                "This payment requires the owner's signature; the settlement key cannot supply it.",
                details={"order_id": str(order.id), "reason": "owner_signature_required"},
            )

        call = self._router.functions.pay(
            self.order_ref(order.id),
            _word(order.nullifier.value, field="nullifier"),
            to_checksum_address(order.payee_address.value),
            order.amount.micro_usdc,
            False,
            b"",
        )
        try:
            raw_hash = await asyncio.to_thread(self._send_sync, call)
        except SettlementRefusal:
            raise
        except Exception as exc:  # provider boundary: every failure is a refusal
            raise self._refusal(exc, stage="submit", order_id=str(order.id)) from exc
        return "0x" + bytes(raw_hash).hex()

    async def anchor(self, anchored_hash: str) -> str:
        """Write a 32-byte reference on-chain and return the anchor tx hash (ADR-006)."""
        data = _word(anchored_hash, field="anchored_hash")
        call = self._router.functions.anchor(data)
        try:
            raw_hash = await asyncio.to_thread(self._send_sync, call)
        except SettlementRefusal:
            raise
        except Exception as exc:  # provider boundary: every failure is a refusal
            raise self._refusal(exc, stage="anchor") from exc
        return "0x" + bytes(raw_hash).hex()

    # ── the order -> calldata mapping (SC-2, SC-9) ───────────────────────────

    @staticmethod
    def order_ref(order_id: OrderId | str) -> bytes:
        """`bytes32` for an off-chain order id: `keccak256` of the identifier string.

        The contract needs a `bytes32` and the domain id is an opaque string; hashing it (rather than a
        bespoke pad/truncate) means any id shape maps losslessly and deterministically, and the mapping
        is reproducible by anyone replaying the log.
        """
        return keccak(text=str(order_id))

    # ── sync internals: web3 is a synchronous client ─────────────────────────

    def _spent_sync(self, nullifier: Nullifier) -> bool:
        spent: bool = self._router.functions.spentNullifiers(
            _word(nullifier.value, field="nullifier")
        ).call()
        return spent

    def _receipt_sync(self, tx_hash: str, order_id: OrderId | None) -> ChainReceipt | None:
        try:
            raw = self._w3.eth.get_transaction_receipt(HexBytes(tx_hash))
        except TransactionNotFound:
            # Not mined yet. `ChainReceipt` would have to invent a block number, so the answer is None.
            return None

        block_number = int(raw["blockNumber"])
        head = int(self._w3.eth.block_number)
        # A mined transaction has at least its own block's confirmation; a reorg that removes it makes
        # the receipt disappear rather than go negative.
        confirmations = max(1, head - block_number + 1)
        status = ReceiptStatus.SUCCESS if int(raw["status"]) == 1 else ReceiptStatus.REVERTED
        gas_used = int(raw["gasUsed"])
        gas_price = int(raw.get("effectiveGasPrice") or self._gas_price_sync(tx_hash))
        reference, is_anchor = self._anchored_ref(raw.get("logs", []))

        return ChainReceipt(
            id=ReceiptId(new_id()),
            # A receipt is a chain fact, not an order fact: the order id is the caller's, or the one the
            # `Anchored` event carries. A revert emits no event, so an unattributed revert falls back to
            # the zero reference and can never conclude a real order (SC-4).
            order_id=order_id or OrderId(reference or _NO_ORDER_REF),
            tx_hash="0x" + bytes(raw["transactionHash"]).hex(),
            block_number=block_number,
            confirmations=confirmations,
            status=status,
            gas_used=gas_used,
            gas_price=str(gas_price),
            fee_usdc_estimate=Money(gas_used * gas_price // self._wei_per_micro_usdc),
            is_anchor=is_anchor,
            revert_reason=self._revert_reason_sync(tx_hash, block_number)
            if status is ReceiptStatus.REVERTED
            else "",
        )

    def _gas_price_sync(self, tx_hash: str) -> int:
        tx = self._w3.eth.get_transaction(HexBytes(tx_hash))
        return int(tx.get("gasPrice") or 0)

    def _anchored_ref(self, logs: Any) -> tuple[str | None, bool]:
        """The `Anchored` event's order reference and whether this was a reference-only write."""
        router = self._router.address.lower()
        for log in logs:
            if str(log["address"]).lower() != router:
                continue
            topics = log.get("topics") or []
            if not topics or "0x" + bytes(topics[0]).hex() != _ANCHORED_TOPIC:
                continue
            order_ref = "0x" + bytes(topics[1]).hex()
            nullifier_ref = "0x" + bytes(topics[2]).hex()
            # `anchor()` names no order and spends no nullifier: that is how an anchor can never be
            # mistaken for a settlement (ADR-006, SC-10).
            return order_ref, order_ref == _NO_ORDER_REF and nullifier_ref == _NO_ORDER_REF
        return None, False

    def _revert_reason_sync(self, tx_hash: str, block_number: int) -> str:
        """Re-execute the transaction to recover *why* it reverted (SC-6).

        A receipt carries the outcome, not the reason. Replaying the call at the transaction's block is
        how the named error (`NullifierSpent`, `OwnerSignatureInvalid`, …) becomes evidence instead of
        an unexplained zero status.
        """
        try:
            tx = self._w3.eth.get_transaction(HexBytes(tx_hash))
            self._w3.eth.call(
                {
                    "from": tx["from"],
                    "to": tx["to"],
                    "value": Wei(int(tx.get("value") or 0)),
                    "data": tx.get("input") or tx.get("data") or b"",
                    "gas": tx["gas"],
                },
                block_identifier=block_number,
            )
        except Exception as exc:  # a revert is the expected path here
            return self._named_error(exc)
        return ""

    def _send_sync(self, call: Any) -> bytes:
        """Estimate, sign (EIP-1559) and broadcast one call. Nothing here is retried.

        Signing is local: the private key never leaves this process, so a compromised RPC endpoint
        cannot redirect the payment — it can only refuse it, and a refusal is a `SettlementRefusal`.
        """
        transaction = call.build_transaction(
            {
                "from": self.payer,
                "value": 0,
                "chainId": self._network.chain_id,
                "nonce": int(self._w3.eth.get_transaction_count(self.payer, "pending")),
                **self._fee_fields(),
            }
        )
        # Headroom on the estimate: a state change between estimation and mining must not turn a
        # settlement into an out-of-gas revert, which the app records as a refusal (SC-6).
        transaction["gas"] = int(transaction["gas"]) * (100 + self._gas_headroom_percent) // 100
        signed = Account.sign_transaction(transaction, self._account.key)
        sent: bytes = bytes(self._w3.eth.send_raw_transaction(signed.raw_transaction))
        return sent

    def _fee_fields(self) -> dict[str, int]:
        """EIP-1559 fees: `maxFeePerGas = 2 * baseFee + priority` (a reorg-safe headroom)."""
        base_fee = int(self._w3.eth.get_block("latest").get("baseFeePerGas") or 0)
        priority = int(self._w3.eth.max_priority_fee)
        return {"maxFeePerGas": base_fee * 2 + priority, "maxPriorityFeePerGas": priority}

    # ── refusal mapping ─────────────────────────────────────────────────────

    def _refusal(self, exc: BaseException, *, stage: str, order_id: str = "") -> SettlementRefusal:
        """Turn any provider failure into a domain refusal with the contract's reason (SC-6)."""
        reason = self._named_error(exc)
        details = {
            "stage": stage,
            "reason": reason,
            "error_type": type(exc).__name__,
        }
        if order_id:
            details["order_id"] = order_id
        return SettlementRefusal(
            ErrorCode.CONFLICT,
            "The chain node refused the settlement transaction; nothing was broadcast.",
            details=details,
        )

    @staticmethod
    def _named_error(exc: BaseException) -> str:
        """The contract's named error if the node reported one, else a short provider phrase."""
        name = named_contract_error(exc)
        if name:
            return name
        text = " ".join(str(exc).split())
        return text[:200] or type(exc).__name__


def _word(value: str, *, field: str) -> bytes:
    """Validate a `0x`-prefixed 32-byte hex value and return its bytes.

    Raises:
        ValidationError: the value is not a `bytes32`. Malformed input is a 422, not a revert and not a
            provider error — the contract would reject it, so the adapter refuses it earlier.
    """
    if not value.startswith("0x") or len(value) != 66:
        raise ValidationError(f"{field} must be 32 bytes of hex", field=field, value=value[:80])
    try:
        return bytes.fromhex(value[2:])
    except ValueError as exc:
        raise ValidationError(f"{field} is not hex", field=field, value=value[:80]) from exc


def revert_payload(exc: BaseException) -> bytes:
    """Extract the raw revert data from a provider exception.

    Two shapes are handled because two providers report it differently: a real node puts `0x`-hex in
    `exc.data` (or in the message), while eth-tester embeds a Python `bytes` repr. Decoding both keeps
    the named-error mapping identical in-process and on a live chain.
    """
    data = getattr(exc, "data", None)
    if isinstance(data, dict):
        data = data.get("data") or data.get("result")
    if isinstance(data, str) and data.startswith("0x"):
        try:
            return bytes.fromhex(data[2:])
        except ValueError:
            pass
    message = str(exc)
    literal = _BYTES_REPR.search(message)
    if literal is not None:
        try:
            decoded = ast.literal_eval(literal.group(0))
        except (ValueError, SyntaxError):
            decoded = None
        if isinstance(decoded, bytes):
            return decoded
    hex_match = re.search(r"0x([0-9a-fA-F]{8,})", message)
    if hex_match is not None:
        try:
            return bytes.fromhex(hex_match.group(1))
        except ValueError:
            pass
    return b""


def named_contract_error(exc: BaseException) -> str:
    """The contract's named error for a refused transaction, or `""` when it is not a named revert.

    Public because the tests assert the *name* (`NullifierSpent`, `OwnerSignatureInvalid`) rather than a
    message: the named error is the contract's refusal vocabulary, and a test that matched a string
    would pass even after the contract renamed its errors.
    """
    payload = revert_payload(exc)
    if len(payload) < 4:
        return ""
    return ROUTER_ERROR_SELECTORS.get("0x" + payload[:4].hex(), "")
