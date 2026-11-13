"""Row ⇄ aggregate translation — the seam that keeps ORM types out of the model.

Canonical: .pi/architecture/modules/mandate.md#components
Reference: .pi/architecture/decisions/ADR-002-data-storage-strategy.md

Two rules make this file worth having instead of using the ORM models directly as domain objects:

1. **Rehydration goes through the aggregate's own constructors where possible**, but a stored
   aggregate must not re-emit its creation events — so mappers rebuild state and then drop the events
   (`_settle()`). Replaying history is not "something happened".
2. **Value objects are reconstructed through their validation**, so a corrupt row fails loudly at the
   boundary (an invalid `Cap` in the database becomes an `InvalidValue`, not a silent zero).
"""

from __future__ import annotations

from src.mandate.domain.constitution import Constitution, ConstitutionVersion, VersionStatus
from src.mandate.domain.entities import Agent, Owner, Payer
from src.mandate.domain.household import Household
from src.mandate.domain.ids import (
    AgentId,
    ConstitutionId,
    HouseholdId,
    OwnerId,
    PayeeId,
    PayerId,
)
from src.mandate.domain.payee import Payee
from src.mandate.domain.values import (
    BankDigest,
    Cap,
    DisplayName,
    EvmAddress,
    PayeeAddress,
    PayeeName,
    PayeeStatus,
    Threshold,
)
from src.mandate.infrastructure.models import (
    ConstitutionRow,
    ConstitutionVersionRow,
    HouseholdRow,
    PayeeRow,
)
from src.shared.domain.event import DomainEvent

__all__ = [
    "constitution_to_domain",
    "constitution_to_row",
    "household_to_domain",
    "household_to_row",
    "payee_to_domain",
    "payee_to_row",
    "version_to_domain",
]


def _settle(aggregate: object) -> None:
    """Rehydration is not a state change: drop the events the factory recorded."""
    pull = getattr(aggregate, "pull_events", None)
    if callable(pull):
        pull()


# ── constitution ────────────────────────────────────────────────────────────
def version_to_domain(row: ConstitutionVersionRow) -> ConstitutionVersion:
    return ConstitutionVersion(
        number=row.number,
        cap=Cap(micro_usdc=row.cap_micro_usdc),
        threshold=Threshold(micro_usdc=row.threshold_micro_usdc),
        require_signature_for_new_payee=row.require_signature_for_new_payee,
        content_hash=row.content_hash,
        status=VersionStatus(row.status),
    )


def constitution_to_domain(row: ConstitutionRow) -> Constitution:
    constitution = Constitution(
        id=ConstitutionId(row.id),
        household_id=HouseholdId(row.household_id),
        version=row.version,
    )
    constitution._versions.extend(version_to_domain(v) for v in row.versions)
    _settle(constitution)
    return constitution


def constitution_to_row(constitution: Constitution) -> ConstitutionRow:
    """Build the row graph for a whole lineage; the caller upserts versions it knows are new."""
    row = ConstitutionRow(
        id=constitution.id,
        household_id=str(constitution.household_id),
        version=constitution.version,
    )
    row.versions = [
        ConstitutionVersionRow(
            constitution_id=constitution.id,
            household_id=str(constitution.household_id),
            number=version.number,
            cap_micro_usdc=version.cap.micro_usdc,
            threshold_micro_usdc=version.threshold.micro_usdc,
            require_signature_for_new_payee=version.require_signature_for_new_payee,
            content_hash=version.content_hash,
            status=version.status.value,
        )
        for version in constitution.versions()
    ]
    return row


# ── household ───────────────────────────────────────────────────────────────
def household_to_domain(row: HouseholdRow) -> Household:
    household = Household(
        id=HouseholdId(row.id),
        owner=Owner(
            id=OwnerId(row.owner_id),
            address=EvmAddress(row.owner_address),
            name=DisplayName(row.owner_name),
        ),
        payer=Payer(
            id=PayerId(row.payer_id),
            name=DisplayName(row.payer_name),
            contact=row.payer_contact,
        ),
        agent=Agent(id=AgentId(row.agent_id), key_id=row.agent_key_id, enabled=row.agent_enabled),
        constitution_id=ConstitutionId(row.constitution_id),
        version=row.version,
    )
    _settle(household)
    return household


def household_to_row(household: Household) -> HouseholdRow:
    return HouseholdRow(
        id=household.id,
        owner_id=household.owner.id,
        owner_address=household.owner.address.value,
        owner_name=household.owner.name.value,
        payer_id=household.payer.id,
        payer_name=household.payer.name.value,
        payer_contact=household.payer.contact,
        agent_id=household.agent.id,
        agent_key_id=household.agent.key_id,
        agent_enabled=household.agent.enabled,
        constitution_id=household.constitution_id,
        version=household.version,
    )


# ── payee ───────────────────────────────────────────────────────────────────
def payee_to_domain(row: PayeeRow) -> Payee:
    payee = Payee(
        id=PayeeId(row.id),
        household_id=HouseholdId(row.household_id),
        name=PayeeName(row.name),
        address=PayeeAddress(row.address),
        verified_digest=BankDigest(hash=row.verified_digest),
        status=PayeeStatus(row.status),
        version=row.version,
    )
    _settle(payee)
    return payee


def payee_to_row(payee: Payee) -> PayeeRow:
    return PayeeRow(
        id=payee.id,
        household_id=str(payee.household_id),
        name=payee.name.value,
        address=payee.address.value,
        verified_digest=payee.verified_digest.hash,
        status=payee.status.value,
        version=payee.version,
    )


def events_to_outbox(events: tuple[DomainEvent, ...]) -> list[dict[str, object]]:
    """Serialise drained events for `mandate_outbox` (ADR-003)."""
    import dataclasses
    import json

    rows: list[dict[str, object]] = []
    for event in events:
        payload = {f.name: getattr(event, f.name) for f in dataclasses.fields(event)}
        payload = {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in payload.items()}
        rows.append(
            {
                "event_id": event.event_id,
                "event_name": event.event_name,
                "aggregate_id": event.aggregate_id,
                "correlation_id": event.correlation_id,
                "payload": json.dumps(payload, sort_keys=True, default=str),
                "occurred_at": event.occurred_at,
            }
        )
    return rows
