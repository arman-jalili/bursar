"""B-5 — a proposal carrying a command path, payee address, cap or threshold is rejected outright.

Canonical: docs/contracts/billing-contract-freeze.md §1
Reference: .pi/architecture/modules/billing.md#components-paymentattempt

Rejection, not sanitization. If the endpoint silently dropped a forbidden field, the caller would learn
which fields survive the filter and send only the ones nobody checks — and the next attempt is a
prompt-injected `payee_address` that reaches `run_command`.
"""

from __future__ import annotations

import pytest

from src.billing.domain.errors import ProposalRejected
from src.billing.domain.payment_attempt import FORBIDDEN_PROPOSAL_KEYS, PaymentAttempt


class TestForbiddenFields:
    @pytest.mark.parametrize(
        "field",
        ["command", "command_path", "payee_address", "cap", "threshold", "is_new_payee"],
    )
    def test_any_forbidden_key_is_refused(self, invoice, field: str) -> None:  # noqa: ANN001
        """B-5: each forbidden key alone is enough to reject the whole proposal."""
        payload = {"invoice_id": invoice.id, field: "0xattacker"}

        with pytest.raises(ProposalRejected):
            PaymentAttempt.from_proposal(payload, invoice)

    def test_a_proposal_without_forbidden_keys_is_accepted(self, invoice) -> None:  # noqa: ANN001
        """B-5: the guard must not refuse legitimate proposals — an ids-only payload is the normal case."""
        PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)

    def test_every_declared_forbidden_key_is_actually_rejected(self, invoice) -> None:  # noqa: ANN001
        """B-5: the constant and the check cannot drift apart.

        Iterating the frozen set means a key added to `FORBIDDEN_PROPOSAL_KEYS` without a guard fails
        here rather than in production.
        """
        for field in sorted(FORBIDDEN_PROPOSAL_KEYS):
            with pytest.raises(ProposalRejected):
                PaymentAttempt.from_proposal({"invoice_id": invoice.id, field: "x"}, invoice)
