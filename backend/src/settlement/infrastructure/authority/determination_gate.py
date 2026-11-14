"""Authority adapters — the dispatch gate and the frozen intent facts, read live.

Canonical: .pi/architecture/modules/settlement.md#dependencies (Depends On: Authority)
Reference: docs/contracts/settlement-contract-freeze.md §2.8 (SC-1)

`AuthorityHttpAdapter` implements the frozen `DeterminationGate` port. SC-1 says the verdict must be
read **now**, at dispatch time: there is no cached-verdict method on the port and there is no cache in
this file. A verdict issued at plan time is not a permission to dispatch — scenario 3 (a payee frozen
between plan and dispatch) passes only because this read is live.

**Fail closed.** Every failure mode — a timeout, a non-200, a body that is not an object, a verdict that
is not one of Authority's three, an answer for a different intent — raises a `SettlementRefusal` naming
the reason. The adapter never invents an `allow`, and there is no default verdict.

The same adapter also reads the intent's frozen facts (`GET /v1/intents/{id}`), because the dispatch use
case needs `PaymentIntentView` (amount, payee address, digest, escalation bits) and the determination
read alone does not carry them. Two fields the Authority aggregate does not store are assembled here and
are documented rather than hidden:

* `household_id` — Mandate's nullifier scope. This deployable is single-household, so it is
  `settings.household_id`; a multi-household deployment reads it from Mandate instead.
* `invoice_hash` — Billing's identity for the bill. The amended nullifier seed is the invoice
  **identity** (`invoice_id`, see the settlement module doc), so the fallback is the intent's own
  `invoice_id`; a Billing read that supplies a content hash would sit here unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

from src.authority.domain.ids import IntentId
from src.authority.domain.values import DeterminationVerdict
from src.mandate.domain.values import BankDigest, PayeeAddress
from src.settlement.domain.errors import SettlementRefusal
from src.settlement.domain.views import DeterminationView, PaymentIntentView
from src.shared.domain.errors import ErrorCode
from src.shared.domain.money import Money
from src.shared.infrastructure.config import Settings

__all__ = [
    "DEMO_AUTHORITY_READ_TOKEN",
    "AuthorityHttpAdapter",
]

#: The demo identity that may read determination/intent state (ADR-005's `authority:read`). Settlement
#: reads it as the owner in the single-household demo; a real deployment issues a dedicated read token.
DEMO_AUTHORITY_READ_TOKEN = "demo-owner-token"

#: Frozen Authority paths (authority module doc, `GET /v1/intents/{id}` / `.../determination`).
_DETERMINATION_PATH = "/v1/intents/{intent_id}/determination"
_INTENT_PATH = "/v1/intents/{intent_id}"


def _authority_origin(precondition_url: str) -> str:
    """`http://127.0.0.1:8001/v1/precondition/check` → `http://127.0.0.1:8001`.

    The gate is the same Authority service the Rigorix precondition client calls, so its origin is
    derived from the configured precondition URL rather than introduced as a second knob that could
    point somewhere else.
    """
    parts = urlsplit(precondition_url)
    if not parts.scheme or not parts.netloc:
        raise SettlementRefusal(
            ErrorCode.VALIDATION_FAILED,
            "precondition_url is not an absolute URL; the Authority gate has no address to read.",
            details={"precondition_url": precondition_url},
        )
    return f"{parts.scheme}://{parts.netloc}"


def _refusal(message: str, *, reason: str, **details: str) -> SettlementRefusal:
    refusal = SettlementRefusal(ErrorCode.CONFLICT, message, details=details)
    refusal.reason_code = reason
    return refusal


def _reason_from_body(response: httpx.Response) -> str:
    """The upstream's own words, when they exist — a refusal should say what Authority said."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:200]
    if isinstance(body, Mapping):
        for key in ("detail", "message"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        error = body.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
    return ""


class AuthorityHttpAdapter:
    """`DeterminationGate` + intent read over Authority's HTTP surface, fail closed (SC-1)."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        read_token: str = DEMO_AUTHORITY_READ_TOKEN,
        transport: httpx.AsyncBaseTransport | None = None,
        household_id: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._read_token = read_token
        self._transport = transport
        self._household_id = household_id

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> AuthorityHttpAdapter:
        """Compose from process configuration; `transport` is the seam tests inject."""
        return cls(
            _authority_origin(settings.precondition_url),
            timeout_seconds=settings.precondition_timeout_seconds,
            read_token=DEMO_AUTHORITY_READ_TOKEN,
            transport=transport,
            household_id=settings.household_id,
        )

    # ── DeterminationGate ───────────────────────────────────────────────────
    async def determination_for(self, intent_id: IntentId) -> DeterminationView:
        """Read the determination in force **now** for this intent (SC-1).

        Raises:
            SettlementRefusal: the read timed out, answered non-200, answered with a malformed body,
                or answered for a different intent. Never returns a permissive default.
        """
        body = await self._get(
            _DETERMINATION_PATH.format(intent_id=str(intent_id)),
            what="determination",
            intent_id=str(intent_id),
        )
        answered_for = str(body.get("intent_id", ""))
        if answered_for and answered_for != str(intent_id):
            raise _refusal(
                "Authority answered for a different intent; a verdict for another payment is not a "
                "permission for this one.",
                reason="authority_intent_mismatch",
                intent_id=str(intent_id),
                answered_for=answered_for,
            )
        raw_verdict = str(body.get("verdict", "")).strip().lower()
        try:
            verdict = DeterminationVerdict(raw_verdict)
        except ValueError as exc:
            raise _refusal(
                f"Authority answered with an unknown verdict {raw_verdict!r}; refusing to dispatch.",
                reason="authority_malformed",
                intent_id=str(intent_id),
                verdict=raw_verdict or "missing",
            ) from exc

        return DeterminationView(
            intent_id=intent_id,
            verdict=verdict,
            # Fail closed: an `escalate` is only a permission once an approval is granted, and this
            # response does not carry that bit. Absent evidence of the owner's signature, it is False.
            approval_granted=body.get("approval_granted") is True,
            determination_id=str(body.get("determination_id", "")),
        )

    # ── intent facts (the dispatch use case's second live read) ────────────
    async def intent_for(self, intent_id: IntentId) -> PaymentIntentView:
        """Read the intent's frozen facts, or refuse (no partial view, no invented amount)."""
        body = await self._get(
            _INTENT_PATH.format(intent_id=str(intent_id)),
            what="intent",
            intent_id=str(intent_id),
        )
        try:
            invoice_id = str(body["invoice_id"])
            return PaymentIntentView(
                intent_id=intent_id,
                invoice_id=invoice_id,
                payee_address=PayeeAddress(str(body["payee_address"])),
                amount=Money(int(str(body["amount_micro_usdc"]))),
                # Billing's content hash wins when present; the amended seed is the invoice identity.
                invoice_hash=str(body.get("invoice_hash") or invoice_id),
                household_id=self._household_id,
                bank_digest=BankDigest(str(body["bank_digest"])),
                is_new_payee=bool(body.get("is_new_payee", False)),
                requires_owner_signature=bool(body.get("requires_owner_signature", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _refusal(
                "Authority answered with an intent that cannot be read; refusing to dispatch.",
                reason="authority_malformed",
                intent_id=str(intent_id),
                problem=str(exc),
            ) from exc

    # ── transport ───────────────────────────────────────────────────────────
    def _client(self) -> httpx.AsyncClient:
        headers = {"Accept": "application/json"}
        if self._read_token:
            headers["Authorization"] = f"Bearer {self._read_token}"
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
            headers=headers,
        )

    async def _get(self, path: str, *, what: str, intent_id: str) -> Mapping[str, object]:
        """One live GET; every failure is a refusal that names the reason."""
        try:
            async with self._client() as client:
                response = await client.get(path)
        except httpx.TimeoutException as exc:
            raise _refusal(
                f"Authority's {what} read timed out after {self._timeout:g}s; refusing to dispatch.",
                reason="authority_timeout",
                intent_id=intent_id,
                path=path,
            ) from exc
        except httpx.HTTPError as exc:
            raise _refusal(
                f"Authority's {what} read failed: {exc}; refusing to dispatch.",
                reason="authority_unreachable",
                intent_id=intent_id,
                path=path,
            ) from exc

        if response.status_code != httpx.codes.OK:
            reason = _reason_from_body(response)
            raise _refusal(
                (
                    f"Authority refused the {what} read with HTTP {response.status_code}"
                    f"{f': {reason}' if reason else ''}; refusing to dispatch."
                ),
                reason="authority_refused",
                intent_id=intent_id,
                status=str(response.status_code),
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise _refusal(
                f"Authority's {what} answer is not JSON; refusing to dispatch.",
                reason="authority_malformed",
                intent_id=intent_id,
            ) from exc
        if not isinstance(body, Mapping):
            raise _refusal(
                f"Authority's {what} answer is not an object; refusing to dispatch.",
                reason="authority_malformed",
                intent_id=intent_id,
            )
        return body
