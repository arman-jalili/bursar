"""Logging — JSON shape, correlation id, and no secrets on the wire.

Canonical: docs/architecture/decisions/ADR-005-authentication-authorization.md
"""

from __future__ import annotations

import json
import logging

import pytest
from src.shared.infrastructure.logging import (
    REDACTED,
    JsonFormatter,
    RedactingFilter,
    configure_logging,
    correlation_id_var,
    get_logger,
)


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="bursar.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="evidence.sealed",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_one_object() -> None:
    payload = json.loads(JsonFormatter().format(_record(envelope_id="e1")))
    assert payload["level"] == "INFO"
    assert payload["msg"] == "evidence.sealed"
    assert payload["envelope_id"] == "e1"


def test_correlation_id_is_attached() -> None:
    token = correlation_id_var.set("corr-123")
    try:
        payload = json.loads(JsonFormatter().format(_record()))
    finally:
        correlation_id_var.reset(token)
    assert payload["correlation_id"] == "corr-123"


@pytest.mark.parametrize("key", ["hmac_key", "settlement_private_key", "api_key", "signature"])
def test_redacting_filter_masks_sensitive_keys(key: str) -> None:
    record = _record(**{key: "super-secret-value"})
    RedactingFilter().filter(record)
    assert getattr(record, key) == REDACTED
    assert "super-secret-value" not in JsonFormatter().format(record)


def test_redacting_filter_leaves_ordinary_fields_alone() -> None:
    record = _record(intent_id="0xabc", amount_usdc="42.50")
    RedactingFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["intent_id"] == "0xabc"
    assert payload["amount_usdc"] == "42.50"


def test_multiline_blobs_are_truncated() -> None:
    record = _record(envelope="x" * 200 + "\n" + "y" * 200)
    RedactingFilter().filter(record)
    assert len(record.envelope) < 100  # type: ignore[attr-defined]


def test_configure_logging_is_idempotent() -> None:
    configure_logging("DEBUG", json_output=True)
    configure_logging("DEBUG", json_output=True)
    assert len(logging.getLogger().handlers) == 1
    assert get_logger("bursar.test").level == logging.NOTSET  # inherits from root
