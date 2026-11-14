"""Shared fixtures for Settlement integration tests (real SQLite, real adapters).

Canonical: .pi/architecture/modules/settlement.md#repository-interfaces-owned-by-domain
Reference: docs/contracts/settlement-contract-freeze.md (SC-3, SC-5, SC-10)

The schema comes from the models, not from a hand-written `CREATE TABLE`, so a test failure here is a
difference between the contract and the real storage layer — not a typo in a fixture.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.authority.domain.values import DeterminationVerdict
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import ChainNetwork
from src.settlement.infrastructure.models import Base
from src.settlement.infrastructure.repositories import SqlSettlementOrderRepository
from src.shared.infrastructure.db import build_engine, build_session_factory

from tests.unit.settlement._fixtures import (
    a_determination,
    an_anvil_network,
    an_intent,
)


@pytest.fixture
async def factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'settlement.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield build_session_factory(engine)
    finally:
        await engine.dispose()


def an_order(
    network: ChainNetwork | None = None,
    *,
    verdict: DeterminationVerdict = DeterminationVerdict.ALLOW,
) -> SettlementOrder:
    """An ORDERED aggregate built through the factory (SC-1), ready to persist."""
    intent = an_intent()
    return SettlementOrder.order(
        intent,
        network or an_anvil_network(),
        a_determination(verdict, intent_id=intent.intent_id),
    )


async def persist(factory: async_sessionmaker[AsyncSession], order: SettlementOrder) -> None:
    """Insert an order and commit — the caller's unit of work is the test's here."""
    session = factory()
    try:
        await SqlSettlementOrderRepository(session).add(order)
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()
