"""AC #7 — a denied determination sets the attempt REFUSED and frees the invoice.

Canonical: docs/architecture/modules/billing.md#acceptance-criteria
Reference: docs/contracts/billing-contract-freeze.md (B-7)

The failure mode this defends is a refusal that still leaves a hole: an attempt that can be dispatched
afterwards, or an invoice stuck in `IN_FLIGHT` so the household can never retry. Both halves are
asserted here, through the application service that applies Authority's verdict.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
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
from src.billing.domain.errors import BillingRefusal
from src.billing.domain.values import AttemptStatus
from src.billing.infrastructure.models import OutboxRow

from tests.integration.billing.conftest import record_command


async def _proposed(factory: async_sessionmaker[AsyncSession]) -> tuple[str, str]:
    recorded = await RecordInvoiceService(factory).execute(record_command())
    proposed = await ProposePaymentService(factory).execute(
        ProposePaymentCommand(invoice_id=recorded.invoice.invoice_id)
    )
    return recorded.invoice.invoice_id, proposed.attempt.attempt_id


class TestRefusalPath:
    @pytest.mark.parametrize(
        ("determination", "reason"),
        [
            ("deny", "not_eligible"),
            ("refused", "authority_refused"),
            ("cap_exceeded", "cap_exceeded"),
            ("payee_frozen", "payee_frozen"),
        ],
    )
    async def test_a_denial_refuses_the_attempt_and_frees_the_invoice(
        self,
        factory: async_sessionmaker[AsyncSession],
        determination: str,
        reason: str,
    ) -> None:
        """AC #7: attempt REFUSED, invoice outstanding, no dispatch."""
        _invoice_id, attempt_id = await _proposed(factory)

        applied = await ApplyDeterminationService(factory).execute(
            ApplyDeterminationCommand(
                attempt_id=attempt_id, determination=determination, reason=reason
            )
        )

        assert applied.attempt.status == AttemptStatus.REFUSED.value
        assert applied.invoice is not None and applied.invoice.status == "outstanding"
        assert applied.events == ("AttemptRefused",)

        async with factory() as session:
            result = await session.execute(
                select(OutboxRow).where(OutboxRow.event_name == "AttemptDispatched")
            )
            assert result.scalar_one_or_none() is None, "a refusal must never dispatch"

    async def test_a_refused_attempt_can_be_proposed_again(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """B-1 vs B-7: the terminal refusal does not lock the invoice forever."""
        invoice_id, attempt_id = await _proposed(factory)
        await ApplyDeterminationService(factory).execute(
            ApplyDeterminationCommand(attempt_id=attempt_id, determination="deny")
        )

        retry = await ProposePaymentService(factory).execute(
            ProposePaymentCommand(invoice_id=invoice_id)
        )

        assert retry.attempt.status == AttemptStatus.PROPOSED.value
        assert retry.attempt.attempt_id != attempt_id

    async def test_an_allow_determination_dispatches(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """B-7 positive case: allow moves the attempt to DISPATCHED and records the fact."""
        _invoice_id, attempt_id = await _proposed(factory)

        applied = await ApplyDeterminationService(factory).execute(
            ApplyDeterminationCommand(attempt_id=attempt_id, determination="allow")
        )

        assert applied.attempt.status == AttemptStatus.DISPATCHED.value
        assert applied.events == ("AttemptDispatched",)
        assert applied.invoice is not None and applied.invoice.status == "in_flight"

    async def test_a_refused_attempt_cannot_be_dispatched_later(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """B-7: terminal means terminal — a late allow verdict is refused, not applied."""
        _, attempt_id = await _proposed(factory)
        await ApplyDeterminationService(factory).execute(
            ApplyDeterminationCommand(attempt_id=attempt_id, determination="deny")
        )

        with pytest.raises(BillingRefusal):
            await ApplyDeterminationService(factory).execute(
                ApplyDeterminationCommand(attempt_id=attempt_id, determination="allow")
            )

    async def test_the_refusal_event_names_the_reason_codes(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        _, attempt_id = await _proposed(factory)
        await ApplyDeterminationService(factory).execute(
            ApplyDeterminationCommand(
                attempt_id=attempt_id, determination="deny", reason="cap_exceeded"
            )
        )

        async with factory() as session:
            result = await session.execute(
                select(OutboxRow).where(OutboxRow.event_name == "AttemptRefused")
            )
            payload = json.loads(result.scalar_one().payload)

        assert payload["reason_codes"] == ["cap_exceeded"]
