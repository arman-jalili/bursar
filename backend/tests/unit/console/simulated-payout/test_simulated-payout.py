"""CON-06 — every payer bill backed by a settlement carries `payout_simulated: true` and the label.

Canonical: .pi/architecture/modules/console.md#anti-corruption-layer--field-whitelists
Reference: docs/contracts/console-contract-freeze.md §1 (CON-06), §2.2, §2.8

The demo moves test funds. A payer bill that reads "Paid" without saying the transfer is simulated
is a false claim about a real household's money — the most expensive sentence this module can print.
"""

from __future__ import annotations

from src.console.application.presentation import PAYER_FORBIDDEN_TERMS, PAYOUT_SIMULATED_LABEL
from src.console.infrastructure.acl import PAYER_BILL_FIELDS, project_payer_bill

SETTLED_UPSTREAM = {
    "invoice_id": "inv-1",
    "payee_name": "Northwind Energy",
    "amount_usdc": "320.00",
    "status": "SETTLED",
    "settled_at": "2026-11-13T14:02:00Z",
    "tx_hash": "0xabc123",
    "payout_simulated": True,
    "internal_note": "operator paid this manually",
}


class TestSimulatedPayout:
    def test_a_settled_bill_keeps_the_simulated_flag(self) -> None:
        """CON-06: the flag is the only thing that makes the "Paid" row honest."""
        bill = project_payer_bill(SETTLED_UPSTREAM)
        assert bill["payout_simulated"] is True

    def test_a_settled_bill_carries_the_demo_label(self) -> None:
        """CON-06: the label travels with the bill; the UI must not have to remember to add it."""
        bill = project_payer_bill(SETTLED_UPSTREAM)
        assert PAYOUT_SIMULATED_LABEL in str(bill)

    def test_the_label_says_the_transfer_is_simulated(self) -> None:
        """CON-06: a bare "Paid" is not enough — the sentence must name the transfer as simulated."""
        lowered = PAYOUT_SIMULATED_LABEL.lower()
        assert "simulated" in lowered
        assert "transfer" in lowered
        assert "demo" in lowered

    def test_the_label_itself_uses_household_vocabulary(self) -> None:
        """CON-05/CON-06: the sentence that explains the demo is still payer-facing copy."""
        for term in PAYER_FORBIDDEN_TERMS:
            assert term not in PAYOUT_SIMULATED_LABEL.lower()

    def test_a_payer_bill_whitelist_keeps_the_flag(self) -> None:
        """CON-06: dropping `payout_simulated` at the ACL would make the label impossible to derive."""
        assert "payout_simulated" in PAYER_BILL_FIELDS
