"""The three catalogued projections (frozen) — read models, never rules.

Canonical: .pi/architecture/modules/console.md#application-services-catalog
Reference: docs/contracts/console-contract-freeze.md §2.7

    ProjectApprovalInbox   FR-024   pending signature requests + owner display reads
    ProjectPayerBills      FR-025   handled/settled bills in household language
    ProjectEvidence                 envelopes + the proxied verified/tampered verdict

No projection takes a session, a repository or a database handle: the console reads other contexts
through their ports. `ProjectApprovalInbox` also serves the payee list and constitution because the
module doc names three projections and a fourth class for two lookup tables would be ceremony.

Nothing business-shaped lives here even once Phase B lands — the console composes, it does not
decide (CON-09). Concretely, each projection does exactly three things: scrub the untrusted port
payload, run it through that surface's whitelist, and build the frozen DTO. It never computes an
amount, a verdict or a status.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime

from src.console.application.dto import (
    ApprovalInboxItem,
    BillStatus,
    ConstitutionReadModel,
    EvidenceReadModel,
    PayeeReadModel,
    PaymentReadModel,
    SignatureOutcome,
    VerificationOutcome,
    VerificationReadModel,
)
from src.console.application.errors import (
    FieldFidelityViolation,
    VerificationRefused,
)
from src.console.application.ports import (
    ApprovalInboxPort,
    BillsPort,
    ConstitutionPort,
    DeterminationPort,
    EvidencePort,
    ReceiptPort,
)
from src.console.application.presentation import (
    PAYOUT_SIMULATED_LABEL,
    payee_status_copy,
    payer_status_copy,
)
from src.console.application.refusals import DenialReasonCode, coerce_code, refusal_copy
from src.console.infrastructure.acl import (
    drop_model_output,
    project_constitution,
    project_evidence,
    project_owner_inbox,
    project_payee,
    project_payer_bill,
    project_verification,
)

__all__ = ["ProjectApprovalInbox", "ProjectEvidence", "ProjectPayerBills"]


# ── Shared coercion ──────────────────────────────────────────────────────────
# The whitelist decides *which* fields cross the boundary; these helpers decide whether the value
# can be represented without changing it. Any coercion (float, lowercasing, truncation) is a
# CON-02 violation and raises — there is deliberately no "best effort" branch.


def _text(values: Mapping[str, object], field: str, surface: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or value == "":
        raise FieldFidelityViolation(
            f"{surface}.{field} must be the exact non-empty string the upstream produced"
        )
    return value


def _optional_text(values: Mapping[str, object], field: str) -> str | None:
    value = values.get(field)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise FieldFidelityViolation(
            f"{field} must be the exact string the upstream produced, not {type(value).__name__}"
        )
    return value


def _flag(values: Mapping[str, object], field: str, surface: str) -> bool:
    value = values.get(field)
    if isinstance(value, bool):
        return value
    raise FieldFidelityViolation(f"{surface}.{field} must be a boolean, not {type(value).__name__}")


def _when(value: object, field: str, surface: str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FieldFidelityViolation(
                f"{surface}.{field} is not an ISO-8601 timestamp: {value!r}"
            ) from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise FieldFidelityViolation(f"{surface}.{field} is missing or not a timestamp")


def _optional_when(value: object, field: str, surface: str) -> datetime | None:
    if value is None or value == "":
        return None
    return _when(value, field, surface)


def _reason_codes(raw: object) -> tuple[DenialReasonCode, ...]:
    """Validate an upstream code list against the frozen set, failing closed (CON-07)."""
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple, set, frozenset)):
        raise FieldFidelityViolation(
            f"reason codes must be a list of codes, not {type(raw).__name__}"
        )
    return tuple(coerce_code(str(code)) for code in raw)


def _bill_status(values: Mapping[str, object]) -> BillStatus:
    raw = values.get("status")
    try:
        return BillStatus(str(getattr(raw, "value", raw)))
    except ValueError as exc:
        raise FieldFidelityViolation(
            f"payer_bill.status {raw!r} is outside the frozen BillStatus set"
        ) from exc


class ProjectApprovalInbox:
    """Projection for the owner: pending signature requests with exact intent fields (FR-024)."""

    def __init__(
        self,
        approvals: ApprovalInboxPort,
        determinations: DeterminationPort,
        constitution: ConstitutionPort,
    ) -> None:
        self._approvals = approvals
        self._determinations = determinations
        self._constitution = constitution

    async def execute(self, owner_scope: str) -> tuple[ApprovalInboxItem, ...]:
        """Return the owner's pending approvals.

        Raises:
            FieldFidelityViolation: a field would be normalised on its way to the screen (CON-02).
            WhitelistViolation: upstream sent a key no owner whitelist names (CON-01).
        """
        pending = await self._approvals.list_pending(owner_scope)
        return tuple(self._item(payload) for payload in pending)

    async def payees(self, owner_scope: str) -> tuple[PayeeReadModel, ...]:
        """Display-only payee list for the owner (CON-01)."""
        del owner_scope  # the port is already scoped by the adapter; this is display only
        payees = await self._constitution.payees()
        return tuple(self._payee(payload) for payload in payees)

    async def constitution_version(self, owner_scope: str) -> ConstitutionReadModel:
        """Current cap/threshold/version for display; the console never publishes one (CON-01)."""
        del owner_scope
        upstream = drop_model_output(await self._constitution.current())
        projected = project_constitution(upstream)
        return ConstitutionReadModel(
            version=_text(projected, "version", "constitution"),
            cap_usdc=_text(projected, "cap_usdc", "constitution"),
            threshold_usdc=_text(projected, "threshold_usdc", "constitution"),
            published_at=_when(projected.get("published_at"), "published_at", "constitution"),
        )

    async def submit(
        self,
        approval_id: str,
        *,
        raw_body: bytes,
        content_type: str,
        owner_scope: str,
    ) -> SignatureOutcome:
        """Forward the owner's signature and translate Authority's answer (CON-03/CON-07).

        The body is handed to the port exactly as received: no parse, no re-order, no injected
        `approval_id`. The console's only work is translating Authority's reason codes.
        """
        del owner_scope  # identity is enforced by the transport's bearer token
        answer = await self._approvals.submit_signature(approval_id, raw_body, content_type)
        codes = _reason_codes(answer.get("reason_codes"))
        granted = answer.get("granted") is True
        if granted:
            return SignatureOutcome(granted=True, reason_plain=None, reason_codes=codes)
        return SignatureOutcome(
            granted=False,
            # Fail closed: a refusal with no translatable code raises RefusalReasonMissing.
            reason_plain=refusal_copy(codes),
            reason_codes=codes,
        )

    def _item(self, payload: Mapping[str, object]) -> ApprovalInboxItem:
        projected = project_owner_inbox(drop_model_output(payload))
        return ApprovalInboxItem(
            approval_id=_text(projected, "approval_id", "owner_inbox"),
            intent_id=_text(projected, "intent_id", "owner_inbox"),
            invoice_id=_text(projected, "invoice_id", "owner_inbox"),
            payee_name=_text(projected, "payee_name", "owner_inbox"),
            payee_address=_text(projected, "payee_address", "owner_inbox"),
            amount_usdc=_text(projected, "amount_usdc", "owner_inbox"),
            bank_digest=_text(projected, "bank_digest", "owner_inbox"),
            is_new_payee=_flag(projected, "is_new_payee", "owner_inbox"),
            requires_owner_signature=_flag(projected, "requires_owner_signature", "owner_inbox"),
            reason_codes=tuple(code.value for code in _reason_codes(projected.get("reason_codes"))),
            expires_at=_when(projected.get("expires_at"), "expires_at", "owner_inbox"),
            typed_data_hash=_text(projected, "typed_data_hash", "owner_inbox"),
        )

    def _payee(self, payload: Mapping[str, object]) -> PayeeReadModel:
        projected = project_payee(drop_model_output(payload))
        status = _text(projected, "status", "payee_list")
        return PayeeReadModel(
            payee_id=_text(projected, "payee_id", "payee_list"),
            display_name=_text(projected, "display_name", "payee_list"),
            status=status,
            status_plain=payee_status_copy(status),
        )


class ProjectPayerBills:
    """Projection for the payer: handled and settled bills, in household language (FR-025)."""

    def __init__(self, bills: BillsPort, receipts: ReceiptPort) -> None:
        self._bills = bills
        self._receipts = receipts

    async def execute(self, scope: str) -> tuple[PaymentReadModel, ...]:
        """Return every bill visible to this payer scope.

        Raises:
            PayoutNotLabelled: a settled bill would be rendered without the demo label (CON-06).
            PayerVocabularyViolation: the resulting copy contains crypto vocabulary (CON-05).
        """
        invoices = await self._bills.list_invoices(scope)
        return tuple([await self._one(invoice) for invoice in invoices])

    async def one(self, scope: str, invoice_id: str) -> PaymentReadModel:
        """Return one bill for the payer detail screen (CON-06)."""
        del scope  # the Billing port is already household-scoped
        return await self._one(await self._bills.get_invoice(invoice_id))

    async def _one(self, invoice: Mapping[str, object]) -> PaymentReadModel:
        invoice_id = _optional_text(invoice, "invoice_id")
        receipt = await self._receipts.receipt_for(invoice_id) if invoice_id else None

        # A receipt fills the settlement columns; it may never overwrite a Billing field with a
        # different value — that would be the console choosing between two upstreams.
        merged: dict[str, object] = dict(invoice)
        if receipt is not None:
            for key in ("settled_at", "tx_hash"):
                if merged.get(key) is None and receipt.get(key) is not None:
                    merged[key] = receipt[key]

        projected = project_payer_bill(drop_model_output(merged))
        status = _bill_status(projected)
        payout_simulated = projected.get("payout_simulated") is True

        refusal_reason: str | None = None
        if status is BillStatus.REFUSED:
            # CON-07: refuse to render a blocked payment without a translatable reason.
            refusal_reason = refusal_copy(_reason_codes(invoice.get("reason_codes")))

        return PaymentReadModel(
            invoice_id=_text(projected, "invoice_id", "payer_bill"),
            payee_name=_text(projected, "payee_name", "payer_bill"),
            amount_usdc=_text(projected, "amount_usdc", "payer_bill"),
            status=status,
            # `payout_label` is the field that carries the demo sentence (CON-06); the status copy
            # itself stays the two-word household status so the row reads "Paid" + label.
            status_plain=payer_status_copy(status, payout_simulated=False),
            settled_at=_optional_when(projected.get("settled_at"), "settled_at", "payer_bill"),
            tx_hash=_optional_text(projected, "tx_hash"),
            payout_simulated=payout_simulated,
            payout_label=PAYOUT_SIMULATED_LABEL if payout_simulated else None,
            refusal_reason=refusal_reason,
        )


class ProjectEvidence:
    """Projection for the owner's evidence viewer: envelopes and the proxied verdict (CON-08)."""

    def __init__(self, evidence: EvidencePort) -> None:
        self._evidence = evidence

    async def envelopes(self, intent_id: str | None) -> tuple[EvidenceReadModel, ...]:
        """List envelopes; hashes and reason codes, never the payload by default (CON-01)."""
        envelopes = await self._evidence.list_envelopes(intent_id)
        return tuple(self._envelope(payload) for payload in envelopes)

    async def verify(self, envelope_id: str) -> VerificationReadModel:
        """Proxy Evidence's verdict so the toggle can show verified/tampered (CON-08).

        Raises:
            VerificationRefused: Evidence could not answer; no verdict is invented.
        """
        try:
            answer = await self._evidence.verify(envelope_id)
        except Exception as exc:
            raise VerificationRefused(
                f"Evidence did not return a verdict for {envelope_id!r}: {exc}"
            ) from exc

        projected = project_verification(drop_model_output(answer))
        raw_outcome = projected.get("outcome")
        try:
            outcome = VerificationOutcome(str(raw_outcome))
        except ValueError as exc:
            raise VerificationRefused(
                f"Evidence returned an unrecognised verdict {raw_outcome!r}; the console has no opinion"
            ) from exc

        checked_at = _optional_when(projected.get("checked_at"), "checked_at", "verification")
        return VerificationReadModel(
            envelope_id=_text(projected, "envelope_id", "verification"),
            outcome=outcome,
            checked_at=checked_at or datetime.now(UTC),
            detail=_optional_text(projected, "detail") or "",
        )

    def _envelope(self, payload: Mapping[str, object]) -> EvidenceReadModel:
        projected = project_evidence(drop_model_output(payload))
        return EvidenceReadModel(
            envelope_id=_text(projected, "envelope_id", "evidence"),
            event_type=_text(projected, "event_type", "evidence"),
            occurred_at=_when(projected.get("occurred_at"), "occurred_at", "evidence"),
            result=_optional_text(projected, "result") or "",
            anchor_tx=_optional_text(projected, "anchor_tx"),
        )
