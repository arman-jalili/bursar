"""AC 15 / A-8 — the domain refuses with domain errors, so no persistence type is needed at the boundary.

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/decisions/ADR-001-architecture-pattern.md

Layer purity expressed as a *rule* rather than as an import scan: every refusal Authority can raise is a
`RefusalError`, so the API layer maps it to a documented 409 with no knowledge of SQLAlchemy. A `ValueError`
escaping the domain becomes a 500 — the exact way an expected refusal gets reported as a server fault.
"""

from __future__ import annotations

import pytest
from src.authority.domain.errors import (
    ApprovalBindingMismatch,
    ApprovalExpired,
    ApprovalSingleUse,
    AuthorityRefusal,
    CapExceeded,
    DeterminationWithoutReason,
    DispatchWithoutAuthority,
    ReservationAlreadyResolved,
)
from src.shared.domain.errors import RefusalError


class TestRefusalVocabularyIsTheBoundary:
    @pytest.mark.parametrize(
        "refusal",
        [
            CapExceeded(25_000_000, 0),
            ReservationAlreadyResolved("r-1", "committed"),
            DeterminationWithoutReason("no version"),
            ApprovalBindingMismatch("amountUsdc"),
            ApprovalSingleUse("a-1"),
            ApprovalExpired("a-1"),
            DispatchWithoutAuthority("deny"),
        ],
    )
    def test_every_refusal_maps_to_the_shared_envelope(self, refusal: RefusalError) -> None:
        """AC 15: one vocabulary, so the transport needs no Authority-specific handling."""
        # One vocabulary: the shared envelope type and this context's base are the same family.
        assert issubclass(type(refusal), RefusalError)
        assert issubclass(type(refusal), AuthorityRefusal)

    def test_a_refusal_carries_a_reason_code(self) -> None:
        """AC 15: the code is what the console translates and evidence seals."""
        assert CapExceeded(25_000_000, 0).reason_code == "cap_exceeded"

    def test_the_domain_refuses_by_raising_not_by_returning_a_sentinel(self) -> None:
        """AC 15/A-8: a returned sentinel can be ignored; an exception cannot."""
        from src.authority.domain.cap_ledger import CapLedger

        from tests.unit.authority._builders import an_intent_id, usdc

        ledger = CapLedger(
            day="2026-11-14", cap=usdc("10"), committed=usdc("10"), reserved=usdc("0")
        )

        with pytest.raises(RefusalError):
            ledger.try_reserve(an_intent_id(), usdc("25"), __import__("datetime").datetime.now())

    def test_authority_refusal_is_the_common_base(self) -> None:
        """AC 15: a caller can catch `AuthorityRefusal` and get every refusal in this context."""
        assert issubclass(CapExceeded, AuthorityRefusal)
        assert issubclass(ApprovalExpired, AuthorityRefusal)
