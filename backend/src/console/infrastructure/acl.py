"""Anti-corruption layer — one explicit whitelist per surface (CON-01).

Canonical: docs/architecture/modules/console.md#anti-corruption-layer--field-whitelists
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

from src.console.application.errors import (
    FieldFidelityViolation,
    PayoutNotLabelled,
    WhitelistViolation,
)
from src.console.application.presentation import PAYOUT_SIMULATED_LABEL

__all__ = [
    "CONSTITUTION_FIELDS",
    "EVIDENCE_FIELDS",
    "FORBIDDEN_UPSTREAM_KEYS",
    "OWNER_INBOX_FIELDS",
    "PAYEE_FIELDS",
    "PAYER_BILL_FIELDS",
    "VERIFICATION_FIELDS",
    "drop_model_output",
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

#: Fields the owner's signature binds. Every one must stay a byte-identical string (CON-02).
_BOUND_FIELDS: Final[tuple[str, ...]] = (
    "payee_address",
    "bank_digest",
    "amount_usdc",
    "typed_data_hash",
)


def drop_model_output(upstream: Mapping[str, object]) -> dict[str, object]:
    """Scrub a port payload at the trust boundary, before a whitelist sees it (CON-01).

    Ports return whatever an upstream service sends. A projection refuses model-output keys loudly
    so a direct caller cannot leak one by accident; a *deployed* projection must still render a
    bill that carries an operator note, so the application service scrubs untrusted payloads here
    first. The scrub is explicit and named — it is not a second projection and adds no field.
    """
    return {key: value for key, value in upstream.items() if key not in FORBIDDEN_UPSTREAM_KEYS}


def _refuse_model_output(upstream: Mapping[str, object], surface: str) -> None:
    present = tuple(key for key in FORBIDDEN_UPSTREAM_KEYS if key in upstream)
    if present:
        raise WhitelistViolation(
            f"{surface} payload carried model-output key(s) {present}; "
            "an un-named key is never screen truth"
        )


def _assert_byte_fidelity(projected: Mapping[str, object], surface: str) -> None:
    for field in _BOUND_FIELDS:
        if field not in projected:
            continue
        value = projected[field]
        if not isinstance(value, str):
            raise FieldFidelityViolation(
                f"{surface}.{field} must be copied as the exact string Authority produced, "
                f"not {type(value).__name__}"
            )


def _narrow(
    upstream: Mapping[str, object],
    fields: tuple[str, ...],
    surface: str,
    *,
    refuse_model_output: bool = True,
) -> dict[str, object]:
    """The one door: copy named fields, drop the rest, refuse model output (CON-01)."""
    if refuse_model_output:
        _refuse_model_output(upstream, surface)
    projected = {key: upstream[key] for key in fields if key in upstream}
    _assert_byte_fidelity(projected, surface)
    return projected


def _status_of(upstream: Mapping[str, object]) -> str:
    raw = upstream.get("status")
    if raw is None:
        return ""
    return str(getattr(raw, "value", raw))


def project_owner_inbox(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for the owner inbox. Unknown keys are dropped, never forwarded (CON-01).

    Raises:
        WhitelistViolation: the payload carries a key in `FORBIDDEN_UPSTREAM_KEYS`.
        FieldFidelityViolation: a copied value would not survive byte-identically (CON-02).
    """
    return _narrow(upstream, OWNER_INBOX_FIELDS, "owner_inbox")


def project_payer_bill(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for a payer bill; settled rows keep `payout_simulated` (CON-01/CON-06).

    A settled row is the one case where a forbidden key is dropped rather than refused: refusing a
    settlement would hide the very row the payer must see, so CON-06's label is enforced instead
    (`PayoutNotLabelled`). Every other caller is refused loudly (CON-01).

    Raises:
        PayoutNotLabelled: a settled bill is missing `payout_simulated: true` (CON-06).
        WhitelistViolation: a non-settled payload carries model output (CON-01).
        FieldFidelityViolation: a copied value would not survive byte-identically (CON-02).
    """
    settled = _status_of(upstream) == "SETTLED"
    projected = _narrow(
        upstream,
        PAYER_BILL_FIELDS,
        "payer_bill",
        refuse_model_output=not settled,
    )

    if settled and projected.get("payout_simulated") is not True:
        raise PayoutNotLabelled(
            "a settled payer bill must carry payout_simulated: true and the demo label"
        )

    # The label travels with the projection so the UI cannot forget it (CON-06).
    projected["payout_label"] = PAYOUT_SIMULATED_LABEL if settled else None
    return projected


def project_payee(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for the owner's display-only payee list (CON-01)."""
    return _narrow(upstream, PAYEE_FIELDS, "payee_list")


def project_constitution(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for the display-only constitution (CON-01)."""
    return _narrow(upstream, CONSTITUTION_FIELDS, "constitution")


def project_evidence(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for an evidence row — no envelope payload (CON-01)."""
    return _narrow(upstream, EVIDENCE_FIELDS, "evidence")


def project_verification(upstream: Mapping[str, object]) -> dict[str, object]:
    """Whitelist projection for Evidence's verdict; never recomputed here (CON-08)."""
    return _narrow(upstream, VERIFICATION_FIELDS, "verification")
