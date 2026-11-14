"""Configuration — one typed Settings object, loaded once, never re-read.

Canonical: docs/architecture/decisions/ADR-005-authentication-authorization.md
Reference: docs/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

Decisions worth defending:

* **Secrets are `SecretStr`.** The HMAC key and the settlement private key are operator-held
  (ADR-005/ADR-007) and must never be printable. `repr(settings)` stays safe by construction; the
  log redactor is a second line of defence, not the only one.
* **`CHAIN` selects the network, not the code path.** Anvil and Base Sepolia differ only in
  `chain_id`, addresses and confirmation count — a single `ChainSettings` view means no
  `if chain == "anvil"` branches leak into the domain.
* **Refuse to boot on a bad config.** A demo that starts with a zero router address and fails
  mid-payment is worse than one that refuses to start.
* Every field is documented in `.env.example`; `tests/test_shared/test_config.py` fails if the two
  drift, which is how the Phase-0 acceptance criterion stays true over time.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["AnchorMode", "ChainName", "Settings", "get_settings", "settings_env_names"]


class ChainName(StrEnum):
    """Settlement network. ADR-007: Anvil is the demo path, Base Sepolia the live claim."""

    ANVIL = "anvil"
    SEPOLIA = "sepolia"


class AnchorMode(StrEnum):
    """Evidence anchoring policy (ADR-006). Recorded on every envelope — batching is labelled."""

    PER_ENVELOPE = "per_envelope"
    BATCHED = "batched"
    DEMO_ONLY = "demo_only"


class Settings(BaseSettings):
    """Process configuration. Environment prefix: `BURSAR_`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BURSAR_",
        extra="ignore",
        frozen=True,
    )

    # ── runtime ─────────────────────────────────────────────────────────────
    env: Literal["local", "ci", "demo", "prod"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    # ── database (ADR-002: SQLite + WAL, one file per deployable) ───────────
    authority_database_url: str = "sqlite+aiosqlite:///./data/authority.db"
    console_database_url: str = "sqlite+aiosqlite:///./data/bursar.db"
    sqlite_busy_timeout_ms: int = Field(default=5000, ge=100, le=60_000)

    # ── mandate / owner identity (ADR-005) ──────────────────────────────────
    owner_address: str = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
    household_id: str = "demo-household"

    # ── evidence signing (ADR-007) ──────────────────────────────────────────
    #: Operator-held. Must not be mounted into the agent workspace.
    hmac_key: SecretStr = SecretStr("change-me-operator-held-evidence-key")
    anchor_mode: AnchorMode = AnchorMode.PER_ENVELOPE

    # ── chain (ADR-007) ─────────────────────────────────────────────────────
    chain: ChainName = ChainName.ANVIL
    rpc_url: str = "http://127.0.0.1:8545"
    chain_id: int = Field(default=31337, ge=1)
    payment_router_address: str = "0x0000000000000000000000000000000000000000"
    usdc_address: str = "0x0000000000000000000000000000000000000000"
    confirmations_required: int = Field(default=1, ge=1, le=64)
    settlement_private_key: SecretStr = SecretStr("")

    # ── spend guard (ADR-006) ───────────────────────────────────────────────
    #: USDC as decimal strings so they parse exactly into `Money`.
    daily_cap_usdc: str = "150"
    per_payment_threshold_usdc: str = "25"
    settlement_budget_usdc: str = "20"

    # ── Rigorix enforcement (ADR-007) ───────────────────────────────────────
    rigorix_base_url: str = "http://127.0.0.1:8080"
    rigorix_api_key: SecretStr = SecretStr("change-me-operator-key")
    precondition_url: str = "http://127.0.0.1:8001/v1/precondition/check"
    #: The Rigorix template whose single `run_command` step IS the payment dispatch
    #: (SC-2: the path comes from the template, never from the caller). Rigorix
    #: `run_command` refuses to spawn anything unless the deployment declares its
    #: boundary, so the template name and the sandbox claim travel together.
    rigorix_run_template: str = "bursar-payment-dispatch"
    #: `container` | `vm` | empty. Empty means "no declared boundary", and Rigorix
    #: then refuses the run_command step instead of pretending filtering is isolation.
    rigorix_sandbox: str = ""
    rigorix_rpc_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    precondition_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    # ── validators ──────────────────────────────────────────────────────────
    @field_validator("owner_address", "payment_router_address", "usdc_address")
    @classmethod
    def _looks_like_evm_address(cls, value: str) -> str:
        if not value.startswith("0x") or len(value) != 42:
            raise ValueError(f"expected a 0x-prefixed 20-byte address, got {value!r}")
        int(value, 16)  # raises on non-hex
        return value

    @field_validator("daily_cap_usdc", "per_payment_threshold_usdc", "settlement_budget_usdc")
    @classmethod
    def _decimal_string(cls, value: str) -> str:
        from decimal import Decimal, InvalidOperation

        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"expected a decimal USDC amount, got {value!r}") from exc
        if parsed < 0:
            raise ValueError(f"USDC amounts cannot be negative, got {value!r}")
        return value

    # ── derived views ───────────────────────────────────────────────────────
    def database_url_for(self, service: Literal["authority", "console"]) -> str:
        """One database file per deployable, so the agent process cannot reach the ledger."""
        return self.authority_database_url if service == "authority" else self.console_database_url

    @property
    def is_demo(self) -> bool:
        return self.env in ("demo", "local")

    def safe_dump(self) -> dict[str, object]:
        """Config for logs and `/readyz`. Secrets are shown as set/unset, never as values."""
        return {
            "env": self.env,
            "chain": str(self.chain),
            "chain_id": self.chain_id,
            "confirmations_required": self.confirmations_required,
            "anchor_mode": str(self.anchor_mode),
            "daily_cap_usdc": self.daily_cap_usdc,
            "per_payment_threshold_usdc": self.per_payment_threshold_usdc,
            "hmac_key_set": bool(self.hmac_key.get_secret_value()),
            "settlement_key_set": bool(self.settlement_private_key.get_secret_value()),
            "rigorix_configured": bool(self.rigorix_api_key.get_secret_value()),
        }


def load_settings(**overrides: object) -> Settings:
    """Build `Settings` with explicit overrides, bypassing `.env`.

    The single sanctioned place for the `_env_file=None` escape hatch: tests and both
    composition roots use this, so a developer's local `.env` can never change a test result.
    Passing unknown keys still fails — only file loading is bypassed, not validation.
    """
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type,call-arg]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Cached: config changes require a restart, deliberately."""
    return Settings()


def settings_env_names() -> tuple[str, ...]:
    """Environment variable names for every field — used by the `.env.example` parity test."""
    prefix = Settings.model_config["env_prefix"] or ""
    return tuple(f"{prefix}{name.upper()}" for name in Settings.model_fields)
