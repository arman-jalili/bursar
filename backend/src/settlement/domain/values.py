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
from dataclasses import dataclass

from src.shared.domain.value_object import ValueObject

__all__ = ["ChainNetwork", "Nullifier", "ReceiptStatus", "SettlementStatus"]


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

    @classmethod
    def derive(cls, invoice_hash: str, scope: str) -> Nullifier:
        """Derive the nullifier from the invoice hash and the household scope (SC-5).

        Raises:
            ValidationError: the invoice hash or scope is empty/malformed.
        """
        raise NotImplementedError("SC-5 — see module doc")

    def same_as(self, other: Nullifier) -> bool:
        """True when both values are the same marker — the local duplicate test (SC-5)."""
        raise NotImplementedError("SC-5 — see module doc")


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

    @classmethod
    def anvil(cls) -> ChainNetwork:
        """Local Anvil configuration (SC-11). Its addresses are not Sepolia's, ever."""
        raise NotImplementedError("SC-11 — see module doc")

    @classmethod
    def base_sepolia(cls) -> ChainNetwork:
        """Base Sepolia configuration (SC-11). Its addresses are not Anvil's, ever."""
        raise NotImplementedError("SC-11 — see module doc")

    @classmethod
    def for_chain(cls, chain_id: int) -> ChainNetwork:
        """Look up a known configuration.

        Raises:
            UnknownNetwork: the chain id has no configuration — refusing is the point, because a
                default network is a hardcoded address waiting to leak (SC-11).
        """
        raise NotImplementedError("SC-11 — see module doc")


class SettlementStatus(enum.StrEnum):
    """SettlementOrder lifecycle. `CONFIRMED`, `REVERTED` and `ABANDONED` are terminal.

    `REVERTED` and `ABANDONED` are terminal on purpose: a revert is a refusal, and an abandoned order
    keeps its tx hash forever. A state that could re-open is how the timeout double-pay happens
    (SC-4, SC-6, SC-8).
    """

    ORDERED = "ordered"
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
