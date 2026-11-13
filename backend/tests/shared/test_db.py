"""Database engine — WAL, busy_timeout, and the unit-of-work scope (ADR-002).

The pragma assertions are the storage half of the cap invariant: without WAL + busy_timeout the
six-split-invoice scenario (scenario 4) fails with "database is locked" instead of a clean refusal.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from src.shared.application.unit_of_work import session_scope
from src.shared.infrastructure.db import (
    build_engine,
    build_session_factory,
    ping,
    sqlite_path,
)


async def test_wal_and_busy_timeout_are_applied(sqlite_engine: AsyncEngine) -> None:
    async with sqlite_engine.connect() as connection:
        journal_mode = (await connection.execute(text("PRAGMA journal_mode"))).scalar()
        busy_timeout = (await connection.execute(text("PRAGMA busy_timeout"))).scalar()
        foreign_keys = (await connection.execute(text("PRAGMA foreign_keys"))).scalar()
    assert str(journal_mode).lower() == "wal"
    assert busy_timeout is not None and int(busy_timeout) == 1234
    assert foreign_keys is not None and int(foreign_keys) == 1


async def test_ping_true_for_live_database(sqlite_engine: AsyncEngine) -> None:
    assert await ping(sqlite_engine) is True


async def test_ping_false_when_database_is_unreachable(tmp_path: Path) -> None:
    """`/readyz` must report not-ready, not crash, when the file cannot be opened (ADR-007)."""
    directory = tmp_path / "gone"
    directory.mkdir()
    engine = build_engine(f"sqlite+aiosqlite:///{directory / 'db.sqlite'}")
    directory.rmdir()  # the parent of the DB file disappears
    try:
        assert await ping(engine) is False
    finally:
        await engine.dispose()


async def test_session_scope_commits_on_success(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        await session.execute(text("CREATE TABLE probe (id INTEGER PRIMARY KEY, v TEXT)"))
        await session.execute(text("INSERT INTO probe (v) VALUES ('kept')"))

    async with session_scope(session_factory) as session:
        count = (await session.execute(text("SELECT COUNT(*) FROM probe"))).scalar()
    assert count == 1


async def test_session_scope_rolls_back_on_exception(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(session_factory) as session:
        await session.execute(text("CREATE TABLE probe (id INTEGER PRIMARY KEY, v TEXT)"))

    with pytest.raises(RuntimeError):
        async with session_scope(session_factory) as session:
            await session.execute(text("INSERT INTO probe (v) VALUES ('discarded')"))
            raise RuntimeError("boom")

    async with session_scope(session_factory) as session:
        count = (await session.execute(text("SELECT COUNT(*) FROM probe"))).scalar()
    assert count == 0


async def test_missing_parent_directory_is_created(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'nested' / 'deep' / 'bursar.db'}"
    engine = build_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        assert Path(sqlite_path(url) or "").parent.is_dir()
    finally:
        await engine.dispose()


def test_sqlite_path_extraction() -> None:
    assert sqlite_path("sqlite+aiosqlite:///./data/x.db") == "./data/x.db"
    assert sqlite_path("postgresql+asyncpg://host/db") is None


def test_session_factory_does_not_expire_aggregates() -> None:
    """A saved aggregate must stay usable inside the same unit of work (ADR-002)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = build_session_factory(build_engine("sqlite+aiosqlite:///:memory:"))
    assert isinstance(factory, async_sessionmaker)
    assert factory.kw["expire_on_commit"] is False
