"""Anti-corruption layer — one explicit whitelist per surface (CON-01).

Canonical: .pi/architecture/modules/console.md#anti-corruption-layer--field-whitelists
Reference: docs/contracts/console-contract-freeze.md §2.8

The whitelist is the **only door** from an upstream payload to a screen. There is deliberately no
`project_all`, no `**upstream` spread and no shared tuple: a convenience wrapper would be a second
door, and a shared tuple would let an owner-only field reach the payer.

`FORBIDDEN_UPSTREAM_KEYS` names the keys that must make a projection *raise* rather than silently
drop. A silent drop is indistinguishable from a typo in the whitelist; a raise names the field in
review. (Dropping is the stated contract; raising is the frozen behaviour so the failure is loud.)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

__all__ = [
    "CONSTITUTION_FIELDS",
    "EVIDENCE_FIELDS",
    "FORBIDDEN_UPSTREAM_KEYS",
    "OWNER_INBOX_FIELDS",
    "PAYEE_FIELDS",
    "PAYER_BILL_FIELDS",
    "VERIFICATION_FIELDS",
    "project_constitution",
    "project_evidence",
    "project_owner_inbox",
    "project_payee",
    "project_payer_bill",
    "project_verification",
]

#: Owner approval inbox (FR-024). `payee_address`, `bank_digest` and `typed_data_hash` are the
#: fields the owner's signature binds (CON-02) and are owner-only (CON-01).
OWNER_INBOX_FIELDS: Final[tuple[str, ...]] = (
    "approval_id",
    "intent_id",
    "invoice_id",
    "payee_name",
    "payee_address",
    "amount_usdc",
    "bank_digest",
    "is_new_payee",
    "requires_owner_signature",
    "reason_codes",
    "expires_at",
    "typed_data_hash",
)

#: Payer bill list (FR-025). No digest, no signature hash: the payer is not the signer (CON-01).
PAYER_BILL_FIELDS: Final[tuple[str, ...]] = (
    "invoice_id",
    "payee_name",
    "amount_usdc",
    "status",
    "settled_at",
    "tx_hash",
    "payout_simulated",
)

PAYEE_FIELDS: Final[tuple[str, ...]] = (
    "payee_id",
    "display_name",
    "status",
)

CONSTITUTION_FIELDS: Final[tuple[str, ...]] = (
    "version",
    "cap_usdc",
    "threshold_usdc",
    "published_at",
)

#: Hashes and reason codes, not payloads: the envelope may hold PII (module doc Open Questions).
EVIDENCE_FIELDS: Final[tuple[str, ...]] = (
    "envelope_id",
    "event_type",
    "occurred_at",
    "result",
    "anchor_tx",
)

#: Evidence's verdict, proxied — the console never adds its own opinion (CON-08).
VERIFICATION_FIELDS: Final[tuple[str, ...]] = (
    "envelope_id",
    "outcome",
    "checked_at",
    "detail",
)

#: Model output that must not become screen truth by accident. A projection raises on these (CON-01).
FORBIDDEN_UPSTREAM_KEYS: Final[tuple[str, ...]] = (
    "internal_note",
    "agent_guess",
    "confidence",
    "reasoning",
    "raw_payload",
)


def project_owner_inbox(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for the owner inbox. Unknown keys are dropped, never forwarded (CON-01).

    Raises:
        WhitelistViolation: the payload carries a key in `FORBIDDEN_UPSTREAM_KEYS`.
        FieldFidelityViolation: a copied value would not survive byte-identically (CON-02).
    """
    raise NotImplementedError("CON-01 — see module doc")


def project_payer_bill(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for a payer bill; settled rows keep `payout_simulated` (CON-01/CON-06)."""
    raise NotImplementedError("CON-01 — see module doc")


def project_payee(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for the owner's display-only payee list (CON-01)."""
    raise NotImplementedError("CON-01 — see module doc")


def project_constitution(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for the display-only constitution (CON-01)."""
    raise NotImplementedError("CON-01 — see module doc")


def project_evidence(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for an evidence row — no envelope payload (CON-01)."""
    raise NotImplementedError("CON-01 — see module doc")


def project_verification(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for Evidence's verdict; never recomputed here (CON-08)."""
    raise NotImplementedError("CON-08 — see module doc")
