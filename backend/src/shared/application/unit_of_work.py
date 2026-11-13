"""UnitOfWork — the one sanctioned place a transaction is opened or closed.

Canonical: .pi/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: .pi/architecture/modules/authority.md#use-cases-and-application-services

The cap invariant (`committed + reserved <= cap`, invariant A-9) is only safe because the check and
the reservation happen inside *one* transaction. That makes transaction placement a domain
guarantee rather than a style preference, which is why:

* repositories never commit — they only participate (`src/shared/domain/repository.py`);
* application services wrap their work in `session_scope(...)` and nothing else commits.

Usage:

    async with session_scope(session_factory) as session:
        ledger = await ledger_repo.for_day(session, day)
        reservation = ledger.try_reserve(intent)
        await ledger_repo.save(session, ledger)
        await outbox.append(session, ledger.pull_events())
    # commit happened on clean exit; a raise rolled everything back

The commit/rollback happens here and nowhere else. The `txn-placement` gate fails the build if that
stops being true.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["session_scope"]


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One unit of work: commit on clean exit, roll back on any exception."""
    session = factory()
    try:
        yield session
    except BaseException:
        await session.rollback()
        raise
    else:
        await session.commit()
    finally:
        await session.close()
