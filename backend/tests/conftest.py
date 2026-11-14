"""Shared test fixtures.

Canonical: docs/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: docs/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

Fixtures keep every test off the developer's real `data/` directory and off their real `.env`:
`Settings(_env_file=None, ...)` with a `tmp_path` database. A test that passes only because of local
state is worse than no test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from src.shared.infrastructure.config import Settings, load_settings
from src.shared.infrastructure.db import build_engine, build_session_factory


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """Isolated settings: temp DBs, no `.env`, HST test values."""
    return load_settings(
        env="ci",
        log_json=True,
        authority_database_url=f"sqlite+aiosqlite:///{tmp_path / 'authority.db'}",
        console_database_url=f"sqlite+aiosqlite:///{tmp_path / 'bursar.db'}",
        hmac_key="test-hmac-key-not-a-secret",
        settlement_private_key="0x" + "11" * 32,
        rigorix_api_key="test-rigorix-key",
    )


@pytest.fixture
def authority_client(tmp_settings: Settings) -> Iterator[TestClient]:
    """`authority-service` app, isolated. `with` block runs the lifespan (engine up/down)."""
    from src.apps.authority_service.app import SERVICE_NAME
    from src.apps.shell import build_app

    with TestClient(build_app(SERVICE_NAME, settings=tmp_settings)) as client:
        yield client


@pytest.fixture
def console_client(tmp_settings: Settings) -> Iterator[TestClient]:
    """`console-api` app **with its contexts installed**, isolated.

    Uses the deployable's real composition root (`console_api.app.build`) rather than `build_app`:
    a test that skips the composition root would pass while the runtime had no routers at all.
    """
    from src.apps.console_api.app import build

    with TestClient(build(tmp_settings)) as client:
        yield client


@pytest_asyncio.fixture
async def sqlite_engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """Real SQLite engine on a temp file — pragmas are only visible on a real connection."""
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'pragmas.db'}", busy_timeout_ms=1234)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(tmp_path: Path) -> async_sessionmaker[AsyncSession]:
    """Real session factory on a temp file, same pragmas as production."""
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'session.db'}")
    return build_session_factory(engine)
