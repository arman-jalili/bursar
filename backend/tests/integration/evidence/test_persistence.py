"""Evidence persistence through the real Alembic schema (E-4/E-5/E-8).

Canonical: docs/architecture/modules/evidence.md#persistence-contract
Reference: docs/contracts/evidence-contract-freeze.md §2.5

The schema is applied by the real migration, not `metadata.create_all`, so the append-only triggers
are part of the proof. These suites fail if the repository grows an update path or if somebody
"fixes" a row with a hand-written UPDATE.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.authority.domain.events import PaymentAllowed
from src.evidence.domain.errors import AppendOnlyViolation
from src.evidence.domain.evidence_envelope import EvidenceEnvelope
from src.evidence.domain.ids import EnvelopeId, EventId
from src.evidence.infrastructure.repositories import (
    SqlEnvelopeRepository,
    SqlProcessedEventRepository,
)
from src.evidence.infrastructure.signer import HmacSigner
from src.shared.application.unit_of_work import session_scope
from src.shared.infrastructure.db import build_engine, build_session_factory
from src.shared.infrastructure.migrations import upgrade_to_head


@pytest_asyncio.fixture
async def factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = f"sqlite+aiosqlite:///{tmp_path / 'evidence.db'}"
    # real migration: tables + append-only triggers. Alembic drives its own loop.
    await asyncio.to_thread(upgrade_to_head, url)
    engine = build_engine(url)
    try:
        yield build_session_factory(engine)
    finally:
        await engine.dispose()


def _envelope() -> EvidenceEnvelope:
    event = PaymentAllowed(
        intent_id="intent-1", amount_micro_usdc=42_500_000, reservation_id="res-1"
    )
    return EvidenceEnvelope.from_event(
        event, signer=HmacSigner("test-hmac-key-not-a-secret"), actor="authority"
    )


class TestAppendOnlySchema:
    async def test_a_direct_update_is_rejected_by_the_trigger(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """E-5: the repository has no update path; the database rejects one too."""
        async with session_scope(factory) as session:
            await SqlEnvelopeRepository(session).append(_envelope())

        with pytest.raises(Exception, match="append-only"):
            async with factory() as session:
                await session.execute(text("UPDATE evidence_envelopes SET payload = '{}'"))
                await session.commit()

    async def test_appending_the_same_id_twice_is_a_violation(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        envelope = _envelope()
        async with factory() as session:
            repository = SqlEnvelopeRepository(session)
            await repository.append(envelope)
            with pytest.raises(AppendOnlyViolation):
                await repository.append(envelope)
            await session.rollback()

    async def test_claim_is_true_once_then_false(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """E-4: the idempotency decision is one atomic insert, not a racy read."""
        event_id = EventId("evt-1")
        async with session_scope(factory) as session:
            repository = SqlProcessedEventRepository(session)
            assert await repository.claim(event_id, "seal") is True
            assert await repository.is_processed(event_id, "seal") is True

        async with session_scope(factory) as session:
            assert await SqlProcessedEventRepository(session).claim(event_id, "seal") is False

    async def test_anchor_hash_is_unique(self, factory: async_sessionmaker[AsyncSession]) -> None:
        """E-8 at the storage layer; the adapter is asserted in the unit suite."""
        envelope = _envelope()
        envelope_hash = envelope.hash().value
        async with session_scope(factory) as session:
            await SqlEnvelopeRepository(session).append(envelope)

        with pytest.raises(IntegrityError):
            async with factory() as session:
                for anchor_id in ("a-1", "a-2"):
                    await session.execute(
                        text(
                            "INSERT INTO evidence_anchors "
                            "(id, envelope_hash, anchor_tx, block_number, chain_id, anchored_at) "
                            "VALUES (:id, :hash, 'tx', 0, 31337, CURRENT_TIMESTAMP)"
                        ),
                        {"id": anchor_id, "hash": envelope_hash},
                    )
                await session.commit()

    async def test_reading_back_reproduces_the_sealed_bytes(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        envelope = _envelope()
        async with session_scope(factory) as session:
            await SqlEnvelopeRepository(session).append(envelope)

        async with session_scope(factory) as session:
            stored = await SqlEnvelopeRepository(session).find_by_id(EnvelopeId(str(envelope.id)))
        assert stored is not None
        assert stored.canonical_bytes() == envelope.canonical_bytes()
        assert stored.hash() == envelope.hash()


class TestWitnessGap:
    async def test_expected_events_are_read_from_the_publisher_outbox(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """E-10: the report compares the publisher's facts with what Evidence sealed."""
        from datetime import UTC, datetime

        from src.evidence.application.services import WitnessReport
        from src.evidence.infrastructure.expected_events import SqlExpectedEvents

        sealed_at = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
        async with session_scope(factory) as session:
            for event_id, event_name in (
                ("evt-sealed", "PaymentAllowed"),
                ("evt-missing", "PaymentRefused"),
            ):
                await session.execute(
                    text(
                        "INSERT INTO billing_outbox "
                        "(event_id, event_name, aggregate_id, payload, occurred_at) "
                        "VALUES (:id, :name, 'agg', '{}', :at)"
                    ),
                    {"id": event_id, "name": event_name, "at": sealed_at},
                )
            await SqlProcessedEventRepository(session).claim(EventId("evt-sealed"), "seal")

        async with session_scope(factory) as session:
            report = WitnessReport(
                expected=SqlExpectedEvents(session),
                processed=SqlProcessedEventRepository(session),
            )
            missing = await report.missing(
                since=datetime(2026, 11, 13, 11, 0, tzinfo=UTC),
                until=datetime(2026, 11, 13, 13, 0, tzinfo=UTC),
            )
        assert missing == ("evt-missing",)
