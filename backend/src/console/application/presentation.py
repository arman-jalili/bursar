"""Presentation contract — the copy tables and the mobile budget, frozen as data.

Canonical: docs/architecture/modules/console.md#anti-corruption-layer--field-whitelists
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
from src.console.application.errors import (
    PayerVocabularyViolation,
    ViewportContractViolation,
)

__all__ = [
    "MAX_APPROVAL_TAPS",
    "MAX_PHONE_WIDTH_PX",
    "MIN_SURFACE_HEIGHT_PX",
    "MIN_SURFACE_WIDTH_PX",
    "MOBILE_VIEWPORT",
    "PAYER_FORBIDDEN_TERMS",
    "PAYER_STATUS_COPY",
    "PAYOUT_SIMULATED_LABEL",
    "Viewport",
    "assert_mobile_contract",
    "payee_status_copy",
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

#: A payee address plus its amount must fit without horizontal scroll at the demo width (CON-10).
MIN_SURFACE_WIDTH_PX: Final[int] = 390
#: The demo is a phone; a tablet/desktop width is not the surface the demo script assumes (CON-10).
MAX_PHONE_WIDTH_PX: Final[int] = 430
MIN_SURFACE_HEIGHT_PX: Final[int] = 844

#: Payer-facing status copy. No entry may contain a term from `PAYER_FORBIDDEN_TERMS` (CON-05).
PAYER_STATUS_COPY: Final[dict[BillStatus, str]] = {
    BillStatus.RECEIVED: "Bill received",
    BillStatus.IN_FLIGHT: "Being paid",
    BillStatus.SETTLED: "Paid",
    BillStatus.REFUSED: "Paused",
}

#: Owner-facing payee status copy — display only, never an action (CON-01, CON-05).
PAYEE_STATUS_COPY: Final[dict[str, str]] = {
    "ACTIVE": "Active",
    "PENDING": "Waiting for your review",
    "QUARANTINED": "Paused while we check this payee",
    "FROZEN": "Paused by the owner",
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


def _assert_household_language(text: str) -> None:
    """Refuse copy that would print crypto vocabulary on a household surface (CON-05)."""
    lowered = text.lower()
    leaked = tuple(term for term in PAYER_FORBIDDEN_TERMS if term in lowered)
    if leaked:
        raise PayerVocabularyViolation(
            f"payer-facing copy contains forbidden vocabulary {leaked}: {text!r}"
        )


def payer_status_copy(status: BillStatus | str, *, payout_simulated: bool) -> str:
    """Render the household-language status for one payer bill (CON-05, CON-06).

    The status is looked up, never derived from a raw upstream string: a new enum member must
    arrive with copy, which is a contract change and shows up in review.

    A settled row is the only row that names the simulated transfer. Whether a settlement *may* be
    rendered without the flag is decided earlier, by `acl.project_payer_bill` (CON-06), which raises
    `PayoutNotLabelled`; this renderer labels when the flag is set and stays silent otherwise so an
    unsettled bill never claims a transfer (the payer-copy suite asserts both directions).

    Raises:
        PayerVocabularyViolation: the status is unknown or the copy leaks crypto vocabulary (CON-05).
    """
    try:
        normalised = BillStatus(status)
    except ValueError as exc:
        raise PayerVocabularyViolation(f"status {status!r} has no household-language copy") from exc

    base = PAYER_STATUS_COPY[normalised]
    text = base
    if normalised is BillStatus.SETTLED and payout_simulated:
        text = f"{base} — {PAYOUT_SIMULATED_LABEL}"

    _assert_household_language(text)
    return text


def payee_status_copy(status: str) -> str:
    """Display copy for a payee status; an unrecognised status reads "Under review".

    Raises:
        PayerVocabularyViolation: the copy leaks crypto vocabulary (CON-05).
    """
    text = PAYEE_STATUS_COPY.get(status, "Under review")
    _assert_household_language(text)
    return text


def payout_label(payout_simulated: bool) -> str:
    """Return the demo label for a simulated payout, or "" when the settlement is not simulated."""
    if not payout_simulated:
        return ""
    _assert_household_language(PAYOUT_SIMULATED_LABEL)
    return PAYOUT_SIMULATED_LABEL


def assert_mobile_contract(viewport: Viewport = MOBILE_VIEWPORT) -> None:
    """Assert both surfaces fit the frozen phone viewport and the approval tap budget (CON-10).

    The check measures the viewport rather than returning early: a narrower phone overflows the
    payee address the owner must verify, and a desktop width is not the surface the demo runs on.

    Raises:
        ViewportContractViolation: the surface needs horizontal scroll or >MAX_APPROVAL_TAPS taps.
    """
    if viewport.width_px < MIN_SURFACE_WIDTH_PX:
        raise ViewportContractViolation(
            f"{viewport.width_px}px is narrower than the {MIN_SURFACE_WIDTH_PX}px the surfaces need "
            "— the payee address would scroll horizontally"
        )
    if viewport.width_px > MAX_PHONE_WIDTH_PX:
        raise ViewportContractViolation(
            f"{viewport.width_px}px is a desktop/tablet width; the demo surfaces are phone surfaces"
        )
    if viewport.height_px < MIN_SURFACE_HEIGHT_PX:
        raise ViewportContractViolation(
            f"{viewport.height_px}px is shorter than the {MIN_SURFACE_HEIGHT_PX}px budget — "
            "the approval button would sit below the fold"
        )
    if MAX_APPROVAL_TAPS > 3:
        raise ViewportContractViolation(
            f"owner approval takes {MAX_APPROVAL_TAPS} taps; the budget is 3"
        )
