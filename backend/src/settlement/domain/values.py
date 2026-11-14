"""Settlement value objects and closed sets (frozen).

Canonical: .pi/architecture/modules/settlement.md#value-objects-entity-vs-vo-justification
Reference: docs/contracts/settlement-contract-freeze.md (SC-5, SC-6, SC-7, SC-11)

    Nullifier       keccak(invoice_hash, scope) — the once-only marker; spending it twice is impossible
    ChainNetwork    chain id + router + USDC + confirmations, bound together (SC-11)
    SettlementStatus  closed set of six states, with three terminal ones (SC-4, SC-6, SC-8)
    ReceiptStatus   chain-level status of one transaction: PENDING / SUCCESS / REVERTED (SC-6, SC-7)

`PayeeAddress` is deliberately absent: it is Mandate's value object (`src.mandate.domain.values`), and
re-declaring it here would create a second definition of a destination — the drift that lets one side
accept an address the other refuses.

The nullifier's only property is that it can be spent once. Two equal nullifiers are the same marker,
not two things, which is exactly why it is a value object and not an entity.

`ChainNetwork` is a configuration value, not a singleton: two networks must never share an address, so
the addresses are fields rather than module constants (SC-11). A hardcoded module-level router address
is how an Anvil run ends up signing a Sepolia transaction.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from eth_hash.auto import keccak

from src.settlement.domain.errors import UnknownNetwork
from src.shared.domain.errors import ValidationError
from src.shared.domain.value_object import ValueObject

__all__ = ["ChainNetwork", "Nullifier", "ReceiptStatus", "SettlementStatus"]

#: A checksummed EVM address, as Mandate validates it (conformist read, not a second definition).
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
#: The exact shape `PaymentRouter.spentNullifiers` stores: 32 bytes, `0x`-prefixed, lower-case.
_BYTES32 = re.compile(r"^0x[0-9a-f]{64}$")

#: Anvil's first two deterministic deploys (router, mock USDC). Local only.
_ANVIL_CHAIN_ID = 31_337
_ANVIL_ROUTER = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
_ANVIL_USDC = "0x0165878A594ca255338adfa4d48449f69242Eb8F"

#: Base Sepolia. The router address is replaced with the deployment output; USDC is Circle's.
#: `test_network_config` exists because a leak between these two pairs is Lock 3 gone (SC-11).
_BASE_SEPOLIA_CHAIN_ID = 84_532
_BASE_SEPOLIA_ROUTER = "0x7A1b9d3f8E2c4a5B6d0E1f23A4b5C6d7E8f90A1b"
_BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


@dataclass(frozen=True, slots=True)
class Nullifier(ValueObject):
    """Derived once-only marker for an invoice within a scope (SC-5, SC-6).

    Value form: a `0x`-prefixed, 32-byte hex string — the exact shape `PaymentRouter.spentNullifiers`
    stores. `derive` is deterministic across processes, because the chain recomputes it: a nullifier
    that differs between the app and the contract is either a duplicate payment or a false refusal.

    The derivation is keccak256 over the invoice hash and the scope. It must stay inside `domain/`
    (AC-12 forbids `web3` here), so Phase B picks a pure keccak implementation — not `hashlib.sha3_256`,
    which is a different function from the EVM's keccak256 and would silently never match.
    """

    value: str

    def __post_init__(self) -> None:
        """Refuse anything that is not the on-chain key shape (SC-5, SC-6).

        Validating here rather than at the call site is the value-object contract: a `Nullifier` that
        exists is one the contract map can address. A malformed marker would compare unequal to the
        spent one on-chain — the duplicate would pay.
        """
        if not _BYTES32.match(self.value):
            raise ValidationError(
                "a nullifier is a 0x-prefixed 32-byte hex value",
                nullifier=self.value,
            )

    @classmethod
    def derive(cls, invoice_hash: str, scope: str) -> Nullifier:
        """Derive the nullifier from the bill's stable identity and the household scope (SC-5).

        `keccak256(invoiceIdentity || scope)` — the EVM's keccak, not `hashlib.sha3_256`. The chain
        recomputes this value; a different function would be a silent duplicate payment or a false
        refusal, which is why the derivation lives in one place and is tested for determinism.

        The seed is encoded as UTF-8 bytes. The parameter keeps the frozen name `invoice_hash` and
        accepts either a 64-hex digest or Billing's opaque invoice id; the callers use the id, because
        the nullifier must key on the identity Billing guarantees for the life of the bill. A
        **content** hash changes when the document is re-issued (a corrected PDF), which would mint a
        second nullifier for the same invoice and defeat scenario 6 — the identity does not.

        Raises:
            ValidationError: the seed or the scope is blank.
        """
        if not invoice_hash or not invoice_hash.strip():
            raise ValidationError("the nullifier seed must not be blank", invoice_hash=invoice_hash)
        if not scope or not scope.strip():
            raise ValidationError("the nullifier scope must not be blank", scope=scope)

        digest = keccak(invoice_hash.encode("utf-8") + scope.encode("utf-8"))
        return cls("0x" + digest.hex())

    def same_as(self, other: Nullifier) -> bool:
        """True when both values are the same marker — the local duplicate test (SC-5)."""
        return self.value == other.value


@dataclass(frozen=True, slots=True)
class ChainNetwork(ValueObject):
    """One chain configuration, bound together (SC-11).

    The four fields travel as a unit on purpose: a `chain_id` without its router address is a
    half-configuration, and a router address without its chain id is how a test run broadcasts to the
    wrong network. `confirmations_required` belongs here too — finality is a property of the network,
    not of a receipt (SC-7).
    """

    chain_id: int
    router_address: str
    usdc_address: str
    confirmations_required: int

    def __post_init__(self) -> None:
        """Refuse a half-configuration (SC-11).

        A `ChainNetwork` that exists is one an adapter can be built from: a chain id, two EVM
        addresses on that chain, and a positive finality depth. Nothing here is optional, because
        every omission would be filled with a default — and a default address is the leak SC-11 names.
        """
        if (
            isinstance(self.chain_id, bool)
            or not isinstance(self.chain_id, int)
            or self.chain_id <= 0
        ):
            raise ValidationError(
                "a chain id must be a positive integer", chain_id=str(self.chain_id)
            )
        if not _EVM_ADDRESS.match(self.router_address):
            raise ValidationError("not an EVM router address", router=self.router_address)
        if not _EVM_ADDRESS.match(self.usdc_address):
            raise ValidationError("not an EVM USDC address", usdc=self.usdc_address)
        if self.confirmations_required < 1:
            raise ValidationError(
                "a network needs at least one confirmation to be final",
                confirmations=str(self.confirmations_required),
            )

    @classmethod
    def anvil(cls) -> ChainNetwork:
        """Local Anvil configuration (SC-11). Its addresses are not Sepolia's, ever."""
        return cls(
            chain_id=_ANVIL_CHAIN_ID,
            router_address=_ANVIL_ROUTER,
            usdc_address=_ANVIL_USDC,
            confirmations_required=1,
        )

    @classmethod
    def base_sepolia(cls) -> ChainNetwork:
        """Base Sepolia configuration (SC-11). Its addresses are not Anvil's, ever.

        Two confirmations is the demo-day proposal from the module doc's open questions; the value is
        not pinned by the contract — what is pinned is that it travels with the addresses (SC-7).
        """
        return cls(
            chain_id=_BASE_SEPOLIA_CHAIN_ID,
            router_address=_BASE_SEPOLIA_ROUTER,
            usdc_address=_BASE_SEPOLIA_USDC,
            confirmations_required=2,
        )

    @classmethod
    def for_chain(cls, chain_id: int) -> ChainNetwork:
        """Look up a known configuration.

        Raises:
            UnknownNetwork: the chain id has no configuration — refusing is the point, because a
                default network is a hardcoded address waiting to leak (SC-11).
        """
        for known in (cls.anvil(), cls.base_sepolia()):
            if known.chain_id == chain_id:
                return known
        raise UnknownNetwork(chain_id)


class SettlementStatus(enum.StrEnum):
    """SettlementOrder lifecycle. `CONFIRMED`, `REVERTED` and `ABANDONED` are terminal.

    `REVERTED` and `ABANDONED` are terminal on purpose: a revert is a refusal, and an abandoned order
    keeps its tx hash forever. A state that could re-open is how the timeout double-pay happens
    (SC-4, SC-6, SC-8).

    `SIGNED` is the state between "an order exists" and "the chain has it": the payment was signed
    locally, so a tx hash **and** the signed bytes are persisted, and nothing has been broadcast yet
    (SC-3). It is a real state, not an error: the governed broadcast step may not have run, may have
    been refused, or the process may have died in between — in every case the order keeps its one hash
    and is recovered by re-broadcasting those same bytes, never by signing again.
    """

    ORDERED = "ordered"
    SIGNED = "signed"
    SUBMITTED = "submitted"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REVERTED = "reverted"
    ABANDONED = "abandoned"


class ReceiptStatus(enum.StrEnum):
    """What the chain says about one transaction. `REVERTED` is a refusal, not a retry (SC-6, SC-8)."""

    PENDING = "pending"
    SUCCESS = "success"
    REVERTED = "reverted"
