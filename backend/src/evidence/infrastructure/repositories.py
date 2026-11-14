"""SQLAlchemy adapters for the frozen Evidence repository ports.

Canonical: .pi/architecture/modules/evidence.md#persistence-contract
Reference: docs/contracts/evidence-contract-freeze.md §2.5

These are the only classes in the module that know a database exists. They never commit: the unit of
work belongs to the application layer (ADR-002).

The append-only rule is not a convention here. `SqlEnvelopeRepository` has **no** `save`, `update`
or `delete`, and the migration installs triggers that abort a direct UPDATE/DELETE as a second line
of defence (E-5). `claim` uses SQLite's `ON CONFLICT DO NOTHING`, so the idempotency decision is made
by the database in one statement rather than by a racy read-then-insert (E-4).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.evidence.domain.anchor import Anchor
from src.evidence.domain.errors import AnchorMismatch, AppendOnlyViolation
from src.evidence.domain.evidence_envelope import EvidenceEnvelope
from src.evidence.domain.ids import EnvelopeId, EventId
from src.evidence.domain.repositories import (
    AnchorRepository,
    EnvelopeRepository,
    ProcessedEventRepository,
)
from src.evidence.domain.values import EnvelopeHash
from src.evidence.infrastructure.mappers import (
    anchor_to_domain,
    anchor_to_row,
    envelope_to_domain,
    envelope_to_row,
)
from src.evidence.infrastructure.models import AnchorRow, EnvelopeRow, ProcessedEventRow

__all__ = [
    "SqlAnchorRepository",
    "SqlEnvelopeRepository",
    "SqlProcessedEventRepository",
]


class SqlEnvelopeRepository(EnvelopeRepository):
    """Append-only persistence for envelopes (E-5)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, envelope: EvidenceEnvelope) -> None:
        self._session.add(envelope_to_row(envelope))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # The only unique key is the id; reaching this means an adapter tried to overwrite.
            raise AppendOnlyViolation(str(envelope.id)) from exc

    async def find_by_id(self, id_: EnvelopeId) -> EvidenceEnvelope | None:
        row = await self._session.get(EnvelopeRow, str(id_))
        return envelope_to_domain(row) if row is not None else None

    async def list_for_subject(
        self,
        *,
        intent_id: str | None = None,
        invoice_id: str | None = None,
        payee_id: str | None = None,
        limit: int = 50,
    ) -> Sequence[EvidenceEnvelope]:
        statement = select(EnvelopeRow).order_by(
            EnvelopeRow.occurred_at.asc(), EnvelopeRow.id.asc()
        )
        if intent_id:
            statement = statement.where(EnvelopeRow.subject_intent_id == intent_id)
        if invoice_id:
            statement = statement.where(EnvelopeRow.subject_invoice_id == invoice_id)
        if payee_id:
            statement = statement.where(EnvelopeRow.subject_payee_id == payee_id)
        statement = statement.limit(max(1, limit))
        result = await self._session.execute(statement)
        return [envelope_to_domain(row) for row in result.scalars().all()]


class SqlAnchorRepository(AnchorRepository):
    """One anchor row per envelope hash (E-8)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, anchor: Anchor) -> None:
        existing = await self.find_for_envelope(anchor.envelope_hash)
        if existing is not None:
            if (
                existing.anchor_tx == anchor.anchor_tx
                and existing.block_number == anchor.block_number
                and existing.chain_id == anchor.chain_id
            ):
                return  # idempotent write: the same hash produced the same receipt
            raise AnchorMismatch(
                envelope_hash=anchor.envelope_hash.value,
                anchor_hash=existing.envelope_hash.value,
                anchor_tx=existing.anchor_tx,
            )
        self._session.add(anchor_to_row(anchor))
        try:
            await self._session.flush()
        except IntegrityError as exc:  # a concurrent writer won the unique hash
            raise AnchorMismatch(
                envelope_hash=anchor.envelope_hash.value,
                anchor_hash=anchor.envelope_hash.value,
                anchor_tx=anchor.anchor_tx,
            ) from exc

    async def find_for_envelope(self, envelope_hash: EnvelopeHash) -> Anchor | None:
        result = await self._session.execute(
            select(AnchorRow).where(AnchorRow.envelope_hash == envelope_hash.value)
        )
        row = result.scalar_one_or_none()
        return anchor_to_domain(row) if row is not None else None


class SqlProcessedEventRepository(ProcessedEventRepository):
    """Idempotency store keyed by `(event_id, handler)` (E-4)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(self, event_id: EventId, handler: str) -> bool:
        statement = (
            sqlite_insert(ProcessedEventRow)
            .values(event_id=str(event_id), handler=handler)
            .on_conflict_do_nothing(index_elements=["event_id", "handler"])
        )
        result = await self._session.execute(statement)
        # rowcount == 1 means the row was inserted (first delivery); 0 means it already existed.
        cursor = cast(CursorResult[Any], result)
        return bool(cursor.rowcount)

    async def is_processed(self, event_id: EventId, handler: str) -> bool:
        result = await self._session.execute(
            select(ProcessedEventRow.event_id).where(
                ProcessedEventRow.event_id == str(event_id),
                ProcessedEventRow.handler == handler,
            )
        )
        return result.scalar_one_or_none() is not None
