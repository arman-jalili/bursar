"""CON-05 — payer-facing copy contains no crypto vocabulary (NFR-017).

Canonical: .pi/architecture/modules/console.md#anti-corruption-layer--field-whitelists
Reference: docs/contracts/console-contract-freeze.md §1 (CON-05), §2.2

A payer does not have a wallet, does not pay gas and does not care what a nullifier is. The check is
case-insensitive because the failure mode is "USDC" in one row and "usdc" in another.
"""

from __future__ import annotations

from src.console.application.dto import BillStatus
from src.console.application.presentation import (
    PAYER_FORBIDDEN_TERMS,
    PAYER_STATUS_COPY,
    payer_status_copy,
)


class TestPayerCopy:
    def test_the_renderer_emits_no_crypto_vocabulary(self) -> None:
        """CON-05: the copy table is data; the renderer is what a screen actually prints."""
        for status in BillStatus:
            text = payer_status_copy(status, payout_simulated=False).lower()
            for term in PAYER_FORBIDDEN_TERMS:
                assert term not in text, f"payer copy for {status} leaks {term!r}: {text!r}"

    def test_no_payer_status_copy_leaks_crypto_vocabulary(self) -> None:
        """CON-05: every row is scanned, not a sample — a copy edit must fail here, not in the demo."""
        for status, text in PAYER_STATUS_COPY.items():
            lowered = text.lower()
            for term in PAYER_FORBIDDEN_TERMS:
                assert term not in lowered, f"payer copy for {status} leaks {term!r}: {text!r}"

    def test_every_bill_status_has_household_language(self) -> None:
        """CON-05: a status with no copy renders as a raw enum, which is also vocabulary leakage."""
        assert set(PAYER_STATUS_COPY) == set(BillStatus)
        assert all(text.strip() for text in PAYER_STATUS_COPY.values())
