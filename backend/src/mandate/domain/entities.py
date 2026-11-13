"""Parties as entities — identity persists, state may change, equality is by identity.

Canonical: .pi/architecture/modules/mandate.md#components
Reference: .pi/architecture/modules/mandate.md#value-objects-with-entity-vs-vo-justification

Why entities and not value objects: an owner is a persisted person with an address that can be
rotated (H-5), a payer is a persisted beneficiary with contact details, and an agent is a persisted
software identity that can be disabled. Two owners with identical fields are still two owners —
which is exactly what `TaskRoot`'s identity-based equality gives us.

Contract (v1): these are thin. They hold identity and the attributes the invariants need, and they
expose **no setters** — the aggregates change them through intention methods
(`household.change_owner(...)`), which is what keeps H-1…H-3 enforceable.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.mandate.domain.ids import AgentId, OwnerId, PayerId
from src.mandate.domain.values import DisplayName, EvmAddress

__all__ = ["Agent", "Owner", "Payer"]


@dataclass(eq=False)
class Owner:
    """The adult child: sole rule-changing and exception-approving authority (H-3, H-5).

    Not an aggregate root: the owner has no lifecycle of its own inside this context — it is
    created with the household and rotated through `Household.change_owner`.
    """

    id: OwnerId
    address: EvmAddress
    name: DisplayName


@dataclass(eq=False)
class Payer:
    """The parent whose bills are paid. Holds no keys and can never authorize (H-2)."""

    id: PayerId
    name: DisplayName
    contact: str = ""


@dataclass(eq=False)
class Agent:
    """The software identity permitted to propose payments — and nothing else (H-2, FR-009).

    `key_id` is an API-key identifier (ADR-005), never key material: the agent's key is issued by
    the operator and is not stored in the domain.
    """

    id: AgentId
    key_id: str
    enabled: bool = True
