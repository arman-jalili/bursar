"""Alembic environment — two databases, one migration tree.

Canonical: docs/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: docs/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

There are two SQLite files (authority + console). Rather than two alembic trees, the target is
selected per run:

    alembic -x db=authority upgrade head
    alembic -x db=console upgrade head

The URL comes from `Settings`, never from `alembic.ini`, so a mistyped URL cannot migrate the wrong
database. `target_metadata` stays `None` in Phase 0: no tables exist and models are added per
context phase (each context owns its own `infrastructure/models.py`).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from src.shared.infrastructure.config import get_settings
from src.shared.infrastructure.db import sqlite_path

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

#: Metadata for every built context, used by `--autogenerate` and by `compare_metadata`.
from src.billing.infrastructure.models import Base as BillingBase  # noqa: E402
from src.evidence.infrastructure.models import Base as EvidenceBase  # noqa: E402
from src.mandate.infrastructure.models import Base as MandateBase  # noqa: E402
from src.settlement.infrastructure.models import Base as SettlementBase  # noqa: E402

target_metadata = [
    MandateBase.metadata,
    BillingBase.metadata,
    SettlementBase.metadata,
    EvidenceBase.metadata,
]


def _selected_database() -> str:
    """`-x db=authority|console`, defaulting to console (the bigger schema)."""
    x_args = context.get_x_argument(as_dictionary=True)
    selected = x_args.get("db", "console")
    if selected not in ("authority", "console"):
        raise SystemExit(f"Unknown database {selected!r}; expected 'authority' or 'console'.")
    return selected


def _database_url() -> str:
    """Resolve the URL and make sure a SQLite file's directory exists.

    An injected `database_url` (set by `src/shared/infrastructure/migrations.py` at app boot) wins:
    the application already resolved the URL, and resolving it twice could target a different file.
    """
    injected = config.attributes.get("database_url")
    if injected:
        path = sqlite_path(str(injected))
        if path:
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        return str(injected)

    # `build_engine` does this for the running services; alembic connects with its own engine, so it
    # has to do the same or the first migration on a clean checkout fails with a bare
    # "unable to open database file".
    settings = get_settings()
    url = settings.database_url_for(_selected_database())  # type: ignore[arg-type]
    path = sqlite_path(url)
    if path:
        Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return url


def run_migrations_offline() -> None:
    """Emit SQL without a DBAPI connection (`--sql`)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite cannot ALTER most columns without a table rebuild
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    engine = async_engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
