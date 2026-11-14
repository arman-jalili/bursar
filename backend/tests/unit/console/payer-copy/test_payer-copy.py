"""CON-05 — payer-facing copy contains no crypto vocabulary (NFR-017).

Canonical: docs/architecture/modules/console.md#anti-corruption-layer--field-whitelists
Reference: docs/contracts/console-contract-freeze.md §1 (CON-05), §2.2

A payer does not have a wallet, does not pay gas and does not care what a nullifier is. The check is
case-insensitive because the failure mode is "USDC" in one row and "usdc" in another.
"""

from __future__ import annotations

from src.console.application.dto import BillStatus
from src.console.application.presentation import (
    PAYER_FORBIDDEN_TERMS,
    payer_status_copy,
    payout_label,
)


class TestPayerCopy:
    def test_the_renderer_emits_no_crypto_vocabulary(self) -> None:
        """CON-05: the copy table is data; the renderer is what a screen actually prints."""
        for status in BillStatus:
            text = payer_status_copy(status, payout_simulated=False).lower()
            for term in PAYER_FORBIDDEN_TERMS:
                assert term not in text, f"payer copy for {status} leaks {term!r}: {text!r}"

    def test_every_bill_status_has_household_language(self) -> None:
        """CON-05: a status with no copy renders as a raw enum, which is also vocabulary leakage."""
        for status in BillStatus:
            text = payer_status_copy(status, payout_simulated=False)
            assert text.strip()
            assert status.value not in text

    def test_a_settled_bill_is_labelled_as_simulated_in_its_copy(self) -> None:
        """CON-05/CON-06: the sentence a payer reads about a settled bill must name the simulation."""
        text = payer_status_copy(BillStatus.SETTLED, payout_simulated=True).lower()
        assert "simulated" in text

    def test_an_unsettled_bill_is_not_labelled_as_simulated(self) -> None:
        """CON-06: a bill with no settlement must not claim a transfer, simulated or otherwise."""
        text = payer_status_copy(BillStatus.RECEIVED, payout_simulated=False).lower()
        assert "simulated" not in text
        assert "transfer" not in text

    def test_the_payout_label_says_the_transfer_is_simulated(self) -> None:
        """CON-06: a bare "Paid" is not enough — the sentence must name the transfer as simulated."""
        lowered = payout_label(True).lower()
        assert "simulated" in lowered
        assert "transfer" in lowered
        assert "demo" in lowered

    def test_the_payout_label_uses_household_vocabulary(self) -> None:
        """CON-05/CON-06: the sentence that explains the demo is still payer-facing copy."""
        lowered = payout_label(True).lower()
        for term in PAYER_FORBIDDEN_TERMS:
            assert term not in lowered
