"""CON-10 — both surfaces fit 390x844 and owner approval stays within three taps (NFR-011).

Canonical: .pi/architecture/modules/console.md#acceptance-criteria
Reference: docs/contracts/console-contract-freeze.md §1 (CON-10), §2.2

The demo is a phone in someone's hand. Horizontal scroll is not a cosmetic defect here: a payee
address that overflows is a field the owner cannot verify before signing.
"""

from __future__ import annotations

import pytest
from src.console.application.errors import ViewportContractViolation
from src.console.application.presentation import (
    MAX_APPROVAL_TAPS,
    MOBILE_VIEWPORT,
    Viewport,
    assert_mobile_contract,
)


class TestMobile:
    def test_both_surfaces_pass_the_frozen_viewport_check(self) -> None:
        """CON-10: the check must actually measure the surfaces, not return early."""
        assert assert_mobile_contract(MOBILE_VIEWPORT) is None

    def test_a_narrower_phone_fails_the_check(self) -> None:
        """CON-10: 320px overflows the payee address, so the contract must refuse it."""
        with pytest.raises(ViewportContractViolation):
            assert_mobile_contract(Viewport(width_px=320, height_px=568))

    def test_the_frozen_viewport_is_the_demo_phone(self) -> None:
        """CON-10: the viewport is data so a UI test and the demo script cannot disagree."""
        assert (MOBILE_VIEWPORT.width_px, MOBILE_VIEWPORT.height_px) == (390, 844)

    def test_the_approval_budget_is_at_most_three_taps(self) -> None:
        """CON-10: four taps from a notification is a lost demo, not a slow one."""
        assert MAX_APPROVAL_TAPS <= 3
