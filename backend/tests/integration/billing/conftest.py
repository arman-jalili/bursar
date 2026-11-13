"""Shared fixtures for Billing integration tests (real SQLite, real adapters)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.billing.application.dto import RecordInvoiceCommand
from src.billing.domain.ids import PayeeId, new_id
from src.billing.infrastructure.models import Base
from src.shared.infrastructure.db import build_engine, build_session_factory

from tests.unit.billing._fixtures import a_digest, a_document

DUE = date(2026, 11, 20)


@pytest.fixture
async def factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'billing.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield build_session_factory(engine)
    finally:
        await engine.dispose()


def record_command(document: dict[str, object] | None = None) -> RecordInvoiceCommand:
    return RecordInvoiceCommand(
        payee_id=str(PayeeId(new_id())),
        amount_micro_usdc=42_500_000,
        due_date=DUE,
        document=document if document is not None else a_document(),
        presented_digest=a_digest().hash,
    )
