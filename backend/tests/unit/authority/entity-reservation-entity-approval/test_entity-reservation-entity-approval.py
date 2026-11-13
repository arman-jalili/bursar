"""A-10 / A-13 — Reservation and Approval are entities with a one-way lifecycle.

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: .pi/architecture/modules/authority.md#components

Both have identity and a lifecycle that two contexts refer to by id, which is what makes them entities
rather than value objects. The rules asserted here are the lifecycle ones: a hold starts HELD, resolves
once, and an approval cannot be conjured into a usable state.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.authority.domain.approval import Approval
from src.authority.domain.cap_ledger import Reservation, ReservationStatus
from src.authority.domain.errors import ApprovalBindingMismatch, ReservationAlreadyResolved
from tests.unit.authority._builders import NOW, an_intent_id, usdc


class TestReservationLifecycle:
    def test_a_new_hold_is_held_and_bound_to_its_day(self) -> None:
        """A-12: the day key is fixed at hold time, so a late settlement cannot move it."""
        reservation = Reservation.hold(
            intent_id=an_intent_id(),
            amount=usdc("25"),
            day="2026-11-14",
            expires_at=NOW + timedelta(minutes=15),
        )

        assert reservation.status is ReservationStatus.HELD
        assert reservation.day == "2026-11-14"

    def test_a_resolved_hold_cannot_be_committed_again(self) -> None:
        """A-10: `mark_committed` on a released hold must raise, not silently re-resolve."""
        reservation = Reservation.hold(
            intent_id=an_intent_id(),
            amount=usdc("25"),
            day="2026-11-14",
            expires_at=NOW + timedelta(minutes=15),
        )
        reservation.mark_released()

        with pytest.raises(ReservationAlreadyResolved):
            reservation.mark_committed()


class TestApprovalLifecycle:
    def test_a_fresh_approval_is_not_usable(self) -> None:
        """A-14: a request with no signature is not an approval — `is_usable` must be False."""
        approval = Approval(
            id="approval-1",  # type: ignore[arg-type]
            intent_id=an_intent_id(),
            typed_data_hash="0xdead",
            expires_at=NOW + timedelta(minutes=15),
        )

        assert approval.is_usable is False

    def test_consuming_an_unverified_approval_is_refused(self) -> None:
        """A-14/A-15: there is no signature, so there is nothing to consume."""
        approval = Approval(
            id="approval-1",  # type: ignore[arg-type]
            intent_id=an_intent_id(),
            typed_data_hash="0xdead",
            expires_at=NOW + timedelta(minutes=15),
        )

        with pytest.raises(ApprovalBindingMismatch):
            approval.consume(now=NOW)
