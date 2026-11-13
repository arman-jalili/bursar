"""Household — the tenancy root and the reason there is exactly one constitution in force.

Canonical: .pi/architecture/modules/mandate.md#aggregate-household
Reference: .pi/architecture/decisions/ADR-001-architecture-pattern.md

Contract (v1) — aggregate root, one consistency boundary (ADR-002):

    H-1  exactly one owner, one payer, one agent
    H-2  the payer never holds a signing capability; the agent never holds a key
    H-3  only a `PartyRef(role=OWNER)` may mutate the household

`open()` is a **factory** rather than a constructor call for a specific reason: creating a household
requires three parties *and* a constitution v1, and a half-built household would be an illegal state
that later code would have to defend against.

Bodies are TODO: the `aggregate-household` implementation item fills them in without changing these
signatures.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.mandate.domain.constitution import Constitution
from src.mandate.domain.entities import Agent, Owner, Payer
from src.mandate.domain.errors import OwnerActionRequired, OwnerProofInvalid
from src.mandate.domain.events import AgentAuthorised, OwnerRegistered, PayerEnrolled
from src.mandate.domain.ids import ConstitutionId, HouseholdId, new_id
from src.mandate.domain.ports import OwnerSignatureProof
from src.mandate.domain.values import PartyRef, Role
from src.shared.domain.aggregate import AggregateRoot

__all__ = ["Household"]


@dataclass(eq=False)
class Household(AggregateRoot):
    """One owner, one payer, one agent, one constitution lineage."""

    id: HouseholdId
    owner: Owner
    payer: Payer
    agent: Agent
    constitution_id: ConstitutionId

    @classmethod
    def open(
        cls,
        *,
        owner: Owner,
        payer: Payer,
        agent: Agent,
        constitution: Constitution,
        actor: PartyRef,
    ) -> Household:
        """Create the household. Emits `OwnerRegistered` + `PayerEnrolled` + `AgentAuthorised`.

        `MandateCreated` is recorded by the application service; the three party events
        (`OwnerRegistered`, `PayerEnrolled`, `AgentAuthorised`) are recorded here, because the
        household is what makes the parties real.
        """
        if actor.role is not Role.OWNER:
            raise OwnerActionRequired(role=actor.role.value)
        household = cls(
            id=HouseholdId(new_id()),
            owner=owner,
            payer=payer,
            agent=agent,
            constitution_id=constitution.id,
        )
        household.record(
            OwnerRegistered(
                aggregate_id=household.id,
                household_id=household.id,
                owner_id=owner.id,
                address=owner.address.value,
            )
        )
        household.record(
            PayerEnrolled(aggregate_id=household.id, household_id=household.id, payer_id=payer.id)
        )
        household.record(
            AgentAuthorised(
                aggregate_id=household.id,
                household_id=household.id,
                agent_id=agent.id,
                constitution_version=constitution.in_force.number,
            )
        )
        return household

    def change_owner(
        self, new_owner: Owner, proof: OwnerSignatureProof, *, actor: PartyRef
    ) -> None:
        """Rotate the owner. Requires the outgoing owner's signature (H-5), not a key.

        Raises:
            OwnerActionRequired: the caller is not the owner.
            OwnerProofInvalid: the signature does not cover (household, new address).
        """
        self.assert_owner_acts(actor)
        if not proof.signs(self.id, new_owner.address):
            raise OwnerProofInvalid("the owner signature does not cover the new owner address")
        self.owner = new_owner
        self.record(
            OwnerRegistered(
                aggregate_id=self.id,
                household_id=self.id,
                owner_id=new_owner.id,
                address=new_owner.address.value,
            )
        )

    def assert_owner_acts(self, actor: PartyRef) -> None:
        """Guard for the H-3 invariant.

        Raises:
            OwnerActionRequired: when `actor.role` is not `Role.OWNER` (agent → HTTP 403).
            OwnerProofInvalid: reserved for the caller's proof check (H-5).
        """
        if actor.role is not Role.OWNER:
            raise OwnerActionRequired(role=actor.role.value, household_id=self.id)
        if actor.household_id and actor.household_id != self.id:
            raise OwnerActionRequired(role=actor.role.value, household_id=actor.household_id)
