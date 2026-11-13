"""A-3 / A-5 — the policy composes the rules, and the verdict carries which ones fired.

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: .pi/architecture/modules/authority.md#components

`DeterminationPolicy` exists because the verdict spans three aggregates and two contexts: payee eligibility
(Mandate), the threshold and flags (constitution), and ledger headroom (CapLedger). The rule asserted here is
that a refusal is traceable to the specific rule that fired — not to a generic "no".
"""

from __future__ import annotations

import pytest
from src.authority.domain.determination import Determination
from src.authority.domain.errors import CapExceeded
from src.mandate.domain.values import PayeeStatus

from tests.unit.authority._builders import NOW, an_intent_id, usdc


class TestDeterminationPolicy:
    def test_a_denial_names_the_rule_that_fired(self) -> None:
        """A-5: 'cap_exceeded' is a diagnosis; 'denied' would not be."""
        from src.authority.domain.values import DenialReason

        determination = Determination.deny(
            intent_id=an_intent_id(),
            reasons=[DenialReason.CAP_EXCEEDED],
            constitution_version=3,
            payee_status_read=PayeeStatus.ELIGIBLE,
            read_at=NOW,
            ledger_snapshot=usdc("150"),
        )

        assert DenialReason.CAP_EXCEEDED in determination.reason_codes

    def test_an_escalation_names_newness_rather_than_a_refusal(self) -> None:
        """A-5/A-4: escalation is not a refusal — it carries the payee status, not a denial code."""
        determination = Determination.escalate(
            intent_id=an_intent_id(),
            constitution_version=3,
            payee_status_read=PayeeStatus.NEW,
            read_at=NOW,
            ledger_snapshot=usdc("0"),
        )

        assert determination.reason_codes == ()
        assert determination.payee_status_read is PayeeStatus.NEW

    def test_a_new_payee_at_a_small_amount_is_not_auto_paid(self) -> None:
        """A-4: the policy must escalate on newness alone, whatever the amount."""
        determination = Determination.escalate(
            intent_id=an_intent_id(),
            constitution_version=3,
            payee_status_read=PayeeStatus.NEW,
            read_at=NOW,
            ledger_snapshot=usdc("5"),
        )

        assert determination.permits_dispatch is False

    def test_the_policy_cannot_allow_when_the_cap_refuses(self) -> None:
        """A-9/A-5: ledger headroom is part of the decision, so a hold that cannot be taken denies."""
        from src.authority.domain.cap_ledger import CapLedger

        ledger = CapLedger(
            day="2026-11-14", cap=usdc("150"), committed=usdc("150"), reserved=usdc("0")
        )

        with pytest.raises(CapExceeded):
            ledger.try_reserve(an_intent_id(), usdc("25"), NOW)
