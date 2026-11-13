"""Database engine factory — SQLite with WAL, sized for one household.

Canonical: .pi/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: .pi/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

The pragmas are not boilerplate, they are the storage half of two invariants:

* `journal_mode=WAL` + `busy_timeout` — a second writer waits instead of failing with
  "database is locked". Without it the cap-reservation UPDATE would error under the exact
  concurrency the domain cares about (six split invoices, scenario 4).
* `synchronous=FULL` — a settlement receipt that survives in memory but not on disk would let the
  ledger and the chain disagree after a crash.

Transaction placement (ADR-002, enforced by the `txn-placement` gate): this module creates engines
and session *factories* but never commits. The unit of work lives in
`src/shared/application/unit_of_work.py`, because ADR-008 forbids transaction handling outside the
application layer — and the cap invariant depends on that rule holding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.shared.infrastructure.logging import get_logger

__all__ = ["build_engine", "build_session_factory", "ping", "sqlite_path"]

logger = get_logger(__name__)

#: Applied to every new SQLite connection. Order matters: WAL first, then the timeout.
_SQLITE_PRAGMAS: tuple[tuple[str, str], ...] = (
    ("journal_mode", "WAL"),
    ("synchronous", "FULL"),
    ("foreign_keys", "ON"),
)


def _ensure_parent_dir(database_url: str) -> None:
    """SQLite will not create a missing directory; a silent in-memory DB would be worse."""
    if not database_url.startswith("sqlite"):
        return
    _, _, raw_path = database_url.partition("///")
    if not raw_path or raw_path.startswith(":memory:"):
        return
    Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def sqlite_path(database_url: str) -> str | None:
    """Filesystem path for a SQLite URL, else None. Used by `/readyz` and tests."""
    if not database_url.startswith("sqlite"):
        return None
    _, _, raw_path = database_url.partition("///")
    return raw_path or None


def _install_pragmas(engine: AsyncEngine, busy_timeout_ms: int) -> None:
    """Attach a connect hook that sets pragmas on every pooled connection."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            for pragma, value in _SQLITE_PRAGMAS:
                cursor.execute(f"PRAGMA {pragma}={value}")
            # `busy_timeout` is the one that turns a lock error into a wait (scenario 4).
            cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        finally:
            cursor.close()


def build_engine(
    database_url: str, *, busy_timeout_ms: int = 5000, echo: bool = False
) -> AsyncEngine:
    """Create an engine for one deployable's database file."""
    _ensure_parent_dir(database_url)
    is_sqlite = database_url.startswith("sqlite")
    engine = create_async_engine(
        database_url,
        echo=echo,
        future=True,
        pool_pre_ping=not is_sqlite,
        # A single writer keeps the ledger serialized (ADR-002). SQLite ignores these for
        # aiosqlite's default pool, but they make the intent explicit for a Postgres move.
        **({"pool_size": 5, "max_overflow": 5} if not is_sqlite else {}),
    )
    if is_sqlite:
        _install_pragmas(engine, busy_timeout_ms)
    logger.info("db.engine.created", extra={"dialect": engine.dialect.name, "sqlite": is_sqlite})
    return engine


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory. `expire_on_commit=False` so aggregates stay usable after save."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def ping(engine: AsyncEngine) -> bool:
    """`/readyz` probe: can we actually reach the database?"""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("db.ping.failed", extra={"error": str(exc)})
        return False
