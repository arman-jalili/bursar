"""AC 14 — authorization comes from a Determination, never from a model.

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/decisions/ADR-007-compliance-engine-architecture.md

Principle 7 of the product: *no LLM in the enforcement path*. The rule is asserted positively — the only
route to dispatch is a verdict from the closed set with a recorded basis — so a "the model said yes" path
has nowhere to exist: there is no free-text verdict and no verdict without a reason code.
"""

from __future__ import annotations

import pytest
from src.authority.domain.determination import Determination
from src.authority.domain.errors import DeterminationWithoutReason
from src.authority.domain.values import DenialReason, DeterminationVerdict
from src.mandate.domain.values import PayeeStatus
from tests.unit.authority._builders import NOW, an_intent_id, usdc


class TestNoLlmInTheEnforcementPath:
    def test_a_free_text_verdict_cannot_be_constructed(self) -> None:
        """AC 14: the verdict is a closed enum, so 'the model says allow' is not expressible."""
        with pytest.raises(ValueError):
            DeterminationVerdict("the model says allow")  # type: ignore[call-arg]

    def test_a_determination_cannot_cite_model_output_as_its_reason(self) -> None:
        """AC 14/A-7: reasons come from the closed set, so prose cannot stand in for a rule."""
        with pytest.raises(DeterminationWithoutReason):
            Determination.deny(
                intent_id=an_intent_id(),
                reasons=["model says deny"],  # type: ignore[list-item]
                constitution_version=3,
                payee_status_read=PayeeStatus.ELIGIBLE,
                read_at=NOW,
                ledger_snapshot=usdc("0"),
            )

    def test_every_decision_records_the_rules_it_consulted(self) -> None:
        """AC 14/A-6: a reproducible decision needs a version and a read time, not a prompt."""
        determination = Determination.allow(
            intent_id=an_intent_id(),
            constitution_version=3,
            payee_status_read=PayeeStatus.ELIGIBLE,
            read_at=NOW,
            ledger_snapshot=usdc("0"),
        )

        assert determination.constitution_version == 3
        assert determination.read_at == NOW

    def test_a_denial_uses_the_closed_reason_set(self) -> None:
        """AC 14/A-5: refusals are codes, which is what makes the path auditable and testable."""
        determination = Determination.deny(
            intent_id=an_intent_id(),
            reasons=[DenialReason.BUDGET_EXHAUSTED],
            constitution_version=3,
            payee_status_read=PayeeStatus.ELIGIBLE,
            read_at=NOW,
            ledger_snapshot=usdc("0"),
        )

        assert determination.reason_codes == (DenialReason.BUDGET_EXHAUSTED,)
