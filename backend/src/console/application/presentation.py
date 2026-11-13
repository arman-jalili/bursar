"""Presentation contract — the copy tables and the mobile budget, frozen as data.

Canonical: .pi/architecture/modules/console.md#anti-corruption-layer--field-whitelists
Reference: docs/contracts/console-contract-freeze.md §2.2

Status → copy is a **lookup table, not a Strategy** (module doc §Patterns): six strings do not
justify a class hierarchy. Freezing it as data means a copy change is a contract change and shows up
in review instead of in a demo.

`PAYER_FORBIDDEN_TERMS` is lowercase so the check is case-insensitive by construction: the failure
mode is "USDC" and "Usdc" in the same screen, not one of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from src.console.application.dto import BillStatus

__all__ = [
    "MAX_APPROVAL_TAPS",
    "MOBILE_VIEWPORT",
    "PAYER_FORBIDDEN_TERMS",
    "PAYER_STATUS_COPY",
    "PAYOUT_SIMULATED_LABEL",
    "Viewport",
    "assert_mobile_contract",
    "payer_status_copy",
    "payout_label",
]


@dataclass(frozen=True, slots=True)
class Viewport:
    """A phone viewport. A dataclass rather than a tuple so a test names what it asserts."""

    width_px: int
    height_px: int


# NFR-011 / CON-10: the demo phone is 390x844; there is no desktop fallback in the demo script.
MOBILE_VIEWPORT: Final[Viewport] = Viewport(width_px=390, height_px=844)
MAX_APPROVAL_TAPS: Final[int] = 3

#: Payer-facing status copy. No entry may contain a term from `PAYER_FORBIDDEN_TERMS` (CON-05).
PAYER_STATUS_COPY: Final[dict[BillStatus, str]] = {
    BillStatus.RECEIVED: "Bill received",
    BillStatus.IN_FLIGHT: "Being paid",
    BillStatus.SETTLED: "Paid",
    BillStatus.REFUSED: "Paused",
}

#: NFR-017: the payer surface is a household surface, not a crypto dashboard.
PAYER_FORBIDDEN_TERMS: Final[tuple[str, ...]] = (
    "usdc",
    "gas",
    "chain",
    "wallet",
    "nullifier",
    "determination",
)

#: CON-06: a demo settlement is always labelled as simulated, in the payer's own words.
PAYOUT_SIMULATED_LABEL: Final[str] = "bank transfer simulated in this demo"


def payer_status_copy(status: BillStatus, *, payout_simulated: bool) -> str:
    """Render the household-language status for one payer bill (CON-05, CON-06).

    Raises:
        PayerVocabularyViolation: the resulting copy contains crypto vocabulary (CON-05).
        PayoutNotLabelled: a settled bill is rendered without the demo label (CON-06).
    """
    raise NotImplementedError("CON-05 — see module doc")


def payout_label(payout_simulated: bool) -> str:
    """Return the demo label for a simulated payout, or "" when the settlement is not simulated."""
    raise NotImplementedError("CON-06 — see module doc")


def assert_mobile_contract(viewport: Viewport = MOBILE_VIEWPORT) -> None:
    """Assert both surfaces fit the frozen phone viewport and the approval tap budget (CON-10).

    Raises:
        ViewportContractViolation: the surface needs horizontal scroll or >MAX_APPROVAL_TAPS taps.
    """
    raise NotImplementedError("CON-10 — see module doc")
