"""SC-5 — a settled invoice cannot be settled twice, locally.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-5)
Reference: docs/architecture/modules/settlement.md#components-nullifier

Defends module AC #5 (scenario 6, app path): a replay of a settled invoice through the API raises
`DuplicateSettlementBlocked` and zero transactions follow. Two halves are asserted here — the derivation
is deterministic (same bill, same marker) and the local guard refuses a spent marker before any chain
call. The database unique constraint is the third half (integration).
"""

from __future__ import annotations

import pytest
from src.settlement.domain.errors import DuplicateSettlementBlocked
from src.settlement.domain.services import NullifierPolicy
from src.settlement.domain.values import Nullifier


class TestNullifierLocal:
    def test_the_same_bill_in_the_same_scope_derives_the_same_marker(self) -> None:
        """SC-5 / AC-5: determinism is what makes two replays collide instead of paying twice."""
        invoice_hash = "ab" * 32
        scope = "hh-1"

        first = Nullifier.derive(invoice_hash, scope)
        second = Nullifier.derive(invoice_hash, scope)

        assert first.same_as(second)

    def test_a_different_scope_derives_a_different_marker(self) -> None:
        """SC-5 / AC-5: scope participates in the derivation, so households cannot consume each other's."""
        invoice_hash = "ab" * 32

        one = Nullifier.derive(invoice_hash, "hh-1")
        two = Nullifier.derive(invoice_hash, "hh-2")

        assert not one.same_as(two)

    def test_a_spent_marker_is_refused_before_any_chain_call(self) -> None:
        """SC-5 / AC-5: the refusal happens locally, so a replay costs zero transactions."""
        marker = Nullifier.derive("ab" * 32, "hh-1")

        with pytest.raises(DuplicateSettlementBlocked):
            NullifierPolicy().guard_unspent(marker, already_spent=True)

    def test_an_unspent_marker_passes_the_guard(self) -> None:
        """SC-5 / AC-5: the guard must not refuse the first, legitimate settlement."""
        marker = Nullifier.derive("ab" * 32, "hh-1")

        NullifierPolicy().guard_unspent(marker, already_spent=False)

    def test_the_policy_derivation_matches_the_order_derivation(self, order) -> None:
        """SC-5 / AC-5: one derivation, two call sites — a second formula would drift."""
        derived = NullifierPolicy().derive(order.invoice_id, "hh-1")

        assert derived.same_as(order.nullifier)
