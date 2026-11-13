"""Settings — typed config, secret hygiene, and `.env.example` parity.

Canonical: .pi/architecture/decisions/ADR-005-authentication-authorization.md
Reference: .pi/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

The parity test is the acceptance criterion made durable: "`.env.example` documents every variable"
is only true until someone adds a field, unless something checks it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from src.shared.infrastructure.config import (
    ChainName,
    load_settings,
    settings_env_names,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _documented_vars() -> set[str]:
    """Active (non-comment) assignments in `.env.example`."""
    return {
        line.split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }


def test_env_example_exists_and_is_not_empty() -> None:
    assert ENV_EXAMPLE.is_file()
    assert len(_documented_vars()) >= 20


def test_every_settings_field_is_documented() -> None:
    documented = _documented_vars()
    missing = sorted(set(settings_env_names()) - documented)
    assert not missing, f"Not documented in .env.example: {missing}"


def test_env_example_documents_nothing_unknown() -> None:
    known = set(settings_env_names())
    extra = sorted(_documented_vars() - known)
    assert not extra, f".env.example documents variables Settings does not read: {extra}"


def test_defaults_load_without_env_file() -> None:
    settings = load_settings()
    assert settings.chain is ChainName.ANVIL
    assert settings.confirmations_required >= 1


def test_secrets_are_not_printable() -> None:
    settings = load_settings(hmac_key="super-secret-hmac")
    assert "super-secret-hmac" not in repr(settings)
    assert "super-secret-hmac" not in str(settings.safe_dump())


def test_safe_dump_reports_set_or_unset_only() -> None:
    secret = "distinctive-test-key-value"
    settings = load_settings(hmac_key=secret)
    dumped = settings.safe_dump()
    assert dumped["hmac_key_set"] is True
    assert secret not in str(dumped)


@pytest.mark.parametrize(
    "bad", ["not-an-address", "0x1234", "f39Fd6e51aad88F6F4ce6aB8827279cffFb92266"]
)
def test_rejects_malformed_address(bad: str) -> None:
    with pytest.raises(ValidationError):
        load_settings(owner_address=bad)


def test_rejects_negative_usdc_amount() -> None:
    with pytest.raises(ValidationError):
        load_settings(daily_cap_usdc="-5")


def test_per_service_database_urls_are_distinct() -> None:
    settings = load_settings()
    assert settings.database_url_for("authority") != settings.database_url_for("console")


def test_anchor_mode_is_a_closed_set() -> None:
    with pytest.raises(ValidationError):
        load_settings(anchor_mode="whenever")


def test_env_example_contains_no_real_secret_looking_values() -> None:
    """A committed key would be the worst possible finding in a public repo."""
    text = ENV_EXAMPLE.read_text()
    # 64-hex-looking blobs (real HMAC keys) must not appear.
    assert not re.search(r"\b[0-9a-f]{64}\b", text, re.IGNORECASE), (
        ".env.example contains a 64-hex value that looks like a real HMAC key"
    )
