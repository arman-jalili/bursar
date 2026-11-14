"""A-6 / A-7 — a determination records the rules it actually consulted.

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/modules/authority.md#aggregate-determination

A-6 is the "re-read at the moment of consequence" rule made auditable: the version and the payee status on
the verdict must come from the same read that produced it, with its timestamp. A-7 forbids an
unexplainable verdict — no reason on a denial, or no version on anything.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.authority.domain.determination import Determination
from src.authority.domain.errors import DeterminationWithoutReason
from src.authority.domain.values import DenialReason
from src.mandate.domain.values import PayeeStatus
from tests.unit.authority._builders import NOW, an_intent_id, usdc


class TestDeterminationRecordsItsBasis:
    def test_a_deny_records_the_version_and_the_payee_status_it_read(self) -> None:
        """A-6: both fields come from the read that decided, so the verdict is reproducible."""
        determination = Determination.deny(
            intent_id=an_intent_id(),
            reasons=[DenialReason.PAYEE_FROZEN],
            constitution_version=3,
            payee_status_read=PayeeStatus.FROZEN,
            read_at=NOW,
            ledger_snapshot=usdc("85"),
        )

        assert determination.constitution_version == 3
        assert determination.payee_status_read is PayeeStatus.FROZEN
        assert determination.read_at == NOW

    def test_the_read_timestamp_is_the_decision_instant_not_the_plan_instant(self) -> None:
        """A-6: scenario 3 — a status read later than the intent's issue time is the whole point."""
        determination = Determination.deny(
            intent_id=an_intent_id(),
            reasons=[DenialReason.PAYEE_FROZEN],
            constitution_version=3,
            payee_status_read=PayeeStatus.FROZEN,
            read_at=NOW + timedelta(minutes=4),
            ledger_snapshot=usdc("85"),
        )

        assert determination.read_at > NOW

    def test_a_denial_without_a_reason_cannot_exist(self) -> None:
        """A-7: no explainable code, no determination — a silent denial is indistinguishable from a bug."""
        with pytest.raises(DeterminationWithoutReason):
            Determination.deny(
                intent_id=an_intent_id(),
                reasons=[],
                constitution_version=3,
                payee_status_read=PayeeStatus.FROZEN,
                read_at=NOW,
                ledger_snapshot=usdc("85"),
            )

    def test_an_allow_carries_no_reason_codes(self) -> None:
        """A-7: an allowance needs no excuse, and inventing one would pollute the evidence."""
        determination = Determination.allow(
            intent_id=an_intent_id(),
            constitution_version=3,
            payee_status_read=PayeeStatus.ELIGIBLE,
            read_at=NOW,
            ledger_snapshot=usdc("85"),
        )

        assert determination.reason_codes == ()

    def test_an_escalation_is_not_a_dispatch_permit(self) -> None:
        """A-8: ESCALATE alone does not permit dispatch — the owner's signature is still missing."""
        determination = Determination.escalate(
            intent_id=an_intent_id(),
            constitution_version=3,
            payee_status_read=PayeeStatus.NEW,
            read_at=NOW,
            ledger_snapshot=usdc("85"),
        )

        assert determination.permits_dispatch is False
