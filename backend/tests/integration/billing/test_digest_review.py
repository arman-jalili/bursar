"""AC #6 — a digest mismatch is reported to Mandate and refused downstream (scenario 2).

Canonical: docs/architecture/modules/billing.md#acceptance-criteria
Reference: docs/contracts/billing-contract-freeze.md (B-4)

Billing's half of scenario 2 is narrow: hand the digest *as presented* to Mandate and record the bill
either way, because the mismatch is evidence. The port returns a view (`matches`, `quarantined`), not
a routing decision. The downstream refusal is modelled by applying the determination that follows the
quarantine — the attempt becomes REFUSED and no reservation exists in this context.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.billing.application.dto import (
    ApplyDeterminationCommand,
    ProposePaymentCommand,
)
from src.billing.application.services_impl import (
    ApplyDeterminationService,
    ProposePaymentService,
    RecordInvoiceService,
)
from src.billing.domain.ports import DigestReview
from src.billing.domain.values import AttemptStatus
from src.mandate.domain.values import BankDigest

from tests.integration.billing.conftest import record_command


class FakeDigestReview:
    """A stand-in for the Mandate adapter; records the exact digest Billing presented."""

    def __init__(self, matches: bool, quarantined: bool) -> None:
        self._review = DigestReview(
            payee_id="payee-1",
            matches=matches,
            quarantined=quarantined,
        )
        self.calls: list[tuple[str, str, str]] = []

    async def review(
        self, *, invoice_id: str, payee_id: str, presented_digest: BankDigest
    ) -> DigestReview:
        self.calls.append((invoice_id, payee_id, presented_digest.hash))
        return self._review


class TestDigestReview:
    async def test_a_mismatch_is_reported_and_the_bill_is_still_recorded(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """B-4: Mandate gets the presented digest; Billing keeps the bill as evidence."""
        fake = FakeDigestReview(matches=False, quarantined=True)
        service = RecordInvoiceService(factory, digest_review=fake)

        recorded = await service.execute(record_command())

        assert len(fake.calls) == 1
        invoice_id, payee_id, digest = fake.calls[0]
        assert invoice_id == recorded.invoice.invoice_id
        assert payee_id == recorded.invoice.payee_id
        assert digest == recorded.invoice.presented_digest
        assert recorded.invoice.status == "received"

    async def test_a_quarantined_payee_refuses_the_attempt_downstream(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Scenario 2: the attempt is refused after quarantine, with no reservation committed."""
        fake = FakeDigestReview(matches=False, quarantined=True)
        recorded = await RecordInvoiceService(factory, digest_review=fake).execute(record_command())
        proposed = await ProposePaymentService(factory).execute(
            ProposePaymentCommand(invoice_id=recorded.invoice.invoice_id)
        )

        applied = await ApplyDeterminationService(factory).execute(
            ApplyDeterminationCommand(
                attempt_id=proposed.attempt.attempt_id,
                determination="payee_quarantined",
                reason="digest_mismatch",
            )
        )

        assert applied.attempt.status == AttemptStatus.REFUSED.value
        assert applied.invoice is not None
        assert applied.invoice.status == "outstanding"
        assert applied.events == ("AttemptRefused",)

    async def test_a_matching_digest_is_a_normal_record(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        fake = FakeDigestReview(matches=True, quarantined=False)
        recorded = await RecordInvoiceService(factory, digest_review=fake).execute(record_command())

        assert recorded.duplicate is False
        assert len(fake.calls) == 1
