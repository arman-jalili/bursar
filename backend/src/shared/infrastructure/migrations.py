"""Schema bootstrap at startup — Alembic is the only definition of the schema.

Canonical: docs/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: docs/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

A developer should be able to run `make run-console` from a clean checkout and have the API work. The
alternative — `Base.metadata.create_all` at boot — would be a *second* definition of the schema that
can silently drift from the migrations. So the app runs the real migrations instead.

This runs in a worker thread: `migrations/env.py` drives its own event loop (Alembic's async recipe),
which cannot be nested inside a running one. One thread at boot is cheaper than a schema that lies.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.shared.infrastructure.logging import get_logger

__all__ = ["alembic_config_path", "upgrade_to_head"]

logger = get_logger(__name__)


def alembic_config_path() -> Path | None:
    """Locate `alembic.ini` from the repo root, or None when running from an installed wheel."""
    for candidate in (Path("alembic.ini"), Path(__file__).resolve().parents[3] / "alembic.ini"):
        if candidate.is_file():
            return candidate
    return None


def upgrade_to_head(database_url: str) -> None:
    """Bring one database to `head`. Never downgrades; safe to call on every boot."""
    config_path = alembic_config_path()
    if config_path is None:
        logger.warning("migrations.skipped", extra={"reason": "alembic.ini not found"})
        return

    from alembic import command
    from alembic.config import Config

    config = Config(str(config_path))
    config.set_main_option("script_location", str(config_path.parent / "migrations"))
    # The URL is injected rather than read from `.env` a second time: the app already resolved it,
    # and a second resolution could pick a different file than the one the engine uses.
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    logger.info("migrations.upgraded", extra={"target": "head"})


async def upgrade_to_head_async(database_url: str) -> None:
    """Run the upgrade off the event loop (Alembic owns its own loop)."""
    try:
        await asyncio.to_thread(upgrade_to_head, database_url)
    except Exception as exc:
        logger.error("migrations.failed", extra={"error": str(exc)})
        raise
