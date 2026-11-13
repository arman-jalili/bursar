"""CON-07 — a refusal reaches the owner as a human reason derived from the closed code set.

Canonical: .pi/architecture/modules/console.md#anti-corruption-layer--field-whitelists
Reference: docs/contracts/console-contract-freeze.md §1 (CON-07), §2.3

Scenarios 2, 3 and 4 all end in a refusal. If the owner sees `DIGEST_MISMATCH` or a generic
"Payment failed", the demo fails its judging criterion: a non-technical viewer must explain *why*
the payment was blocked.
"""

from __future__ import annotations

import pytest
from src.console.application.errors import RefusalReasonMissing
from src.console.application.refusals import REFUSAL_COPY, DenialReasonCode, refusal_copy


class TestRefusalReason:
    def test_a_refusal_renders_the_household_reason_for_its_code(self) -> None:
        """CON-07: the copy table is the contract; the renderer must not paraphrase it per call."""
        assert (
            refusal_copy((DenialReasonCode.DIGEST_MISMATCH,))
            == REFUSAL_COPY[DenialReasonCode.DIGEST_MISMATCH]
        )

    def test_the_rendered_reason_never_contains_the_raw_code(self) -> None:
        """CON-07: SCREAMING_SNAKE on screen is the raw code with extra steps."""
        for code in DenialReasonCode:
            text = refusal_copy((code,))
            assert code.value not in text
            assert "_" not in text

    def test_a_refusal_with_no_code_cannot_be_rendered(self) -> None:
        """CON-07: a refusal with no reason becomes "Payment failed", which explains nothing."""
        with pytest.raises(RefusalReasonMissing):
            refusal_copy(())

    def test_every_denial_code_has_a_household_language_reason(self) -> None:
        """CON-07: a code without copy is a refusal the owner cannot act on."""
        for code in DenialReasonCode:
            text = refusal_copy((code,))
            assert text.strip()
            assert code.value not in text
