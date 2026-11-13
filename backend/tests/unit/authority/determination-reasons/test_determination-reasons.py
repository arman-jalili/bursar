"""A-5 / A-7 — every denial carries a code from the closed set (AC 6).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: .pi/architecture/modules/authority.md#aggregate-determination

The set is closed for a reason: the console translates the code, Evidence seals it, and a test asserts it.
A free-text reason would break all three, so a code outside the set must be rejected rather than stored.
"""

from __future__ import annotations

import pytest
from src.authority.domain.determination import Determination
from src.authority.domain.errors import DeterminationWithoutReason
from src.authority.domain.values import DenialReason
from src.mandate.domain.values import PayeeStatus
from tests.unit.authority._builders import NOW, an_intent_id, usdc


class TestDeterminationReasons:
    @pytest.mark.parametrize("reason", list(DenialReason))
    def test_every_closed_set_code_can_carry_a_denial(self, reason: DenialReason) -> None:
        """A-5: each code is reachable, so a verdict is never forced into a wrong code."""
        determination = Determination.deny(
            intent_id=an_intent_id(),
            reasons=[reason],
            constitution_version=3,
            payee_status_read=PayeeStatus.ELIGIBLE,
            read_at=NOW,
            ledger_snapshot=usdc("0"),
        )

        assert reason in determination.reason_codes

    def test_a_code_outside_the_closed_set_is_refused(self) -> None:
        """A-5/A-7: 'because I said so' is not a reason code — construction must fail."""
        with pytest.raises(DeterminationWithoutReason):
            Determination.deny(
                intent_id=an_intent_id(),
                reasons=["because-the-model-said-so"],  # type: ignore[list-item]
                constitution_version=3,
                payee_status_read=PayeeStatus.ELIGIBLE,
                read_at=NOW,
                ledger_snapshot=usdc("0"),
            )

    def test_several_codes_are_kept_in_order(self) -> None:
        """A-5: a verdict may have several causes (frozen *and* cap), and the order is the diagnosis."""
        determination = Determination.deny(
            intent_id=an_intent_id(),
            reasons=[DenialReason.PAYEE_FROZEN, DenialReason.CAP_EXCEEDED],
            constitution_version=3,
            payee_status_read=PayeeStatus.FROZEN,
            read_at=NOW,
            ledger_snapshot=usdc("150"),
        )

        assert determination.reason_codes == (
            DenialReason.PAYEE_FROZEN,
            DenialReason.CAP_EXCEEDED,
        )

    def test_a_denial_cannot_be_dispatched(self) -> None:
        """A-8: the guard refuses, so a caller cannot act on a DENY even by accident."""
        determination = Determination.deny(
            intent_id=an_intent_id(),
            reasons=[DenialReason.PAYEE_FROZEN],
            constitution_version=3,
            payee_status_read=PayeeStatus.FROZEN,
            read_at=NOW,
            ledger_snapshot=usdc("0"),
        )

        from src.authority.domain.errors import DispatchWithoutAuthority

        with pytest.raises(DispatchWithoutAuthority):
            determination.assert_not_a_refusal()
