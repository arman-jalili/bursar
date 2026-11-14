"""A-1 / A-13 — the modelling line: what is immutable, what has identity, what is a closed set.

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/modules/authority.md#value-objects-entity-vs-vo-justification

Asserted as rules rather than type reflection:

* an issued `PaymentIntent` cannot be mutated (A-1);
* `Reservation` and `Approval` have identity and a lifecycle, so two of them are never interchangeable (A-10,
  A-14);
* the verdict vocabulary is closed, so an unknown verdict cannot be manufactured (A-5).
"""

from __future__ import annotations

import pytest
from src.authority.domain.approval import Approval, OwnerSignature
from src.authority.domain.cap_ledger import Reservation
from src.authority.domain.ids import new_id
from src.authority.domain.payment_intent import PaymentIntent
from src.authority.domain.values import DeterminationVerdict

from tests.unit.authority._builders import NOW, StubMandateView, an_attempt, an_invoice


class TestModelingLine:
    def test_an_issued_intent_is_immutable(self) -> None:
        """A-1: identity plus immutability — the intent is final the moment it is issued."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())

        with pytest.raises(AttributeError):
            intent.constitution_version = 99

    def test_two_reservations_are_not_interchangeable(self) -> None:
        """A-10: identity matters — resolving one must not resolve the other."""
        first = Reservation.hold(an_intent_id_placeholder(), invoice_amount(), "2026-11-14", NOW)
        second = Reservation.hold(an_intent_id_placeholder(), invoice_amount(), "2026-11-14", NOW)

        assert first != second

    def test_an_owner_signature_is_a_value_and_compares_by_content(self) -> None:
        """A-13/A-15: two identical proofs are the same proof; nothing is tracked about them."""
        from src.mandate.domain.values import EvmAddress

        owner = EvmAddress("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")
        assert OwnerSignature(signature_hex="0xs", signer=owner) == OwnerSignature(
            signature_hex="0xs", signer=owner
        )

    def test_the_verdict_set_is_closed(self) -> None:
        """A-5: three verdicts, no fourth — anything else cannot be constructed."""
        assert {v.value for v in DeterminationVerdict} == {"allow", "deny", "escalate"}
        with pytest.raises(ValueError):
            DeterminationVerdict("probably")  # type: ignore[call-arg]

    def test_an_approval_has_identity_so_two_requests_are_distinct(self) -> None:
        """A-13: two signature requests for one intent are still two requests, each single-use."""
        one = Approval(
            id=new_id(),  # type: ignore[arg-type]
            intent_id=new_id(),  # type: ignore[arg-type]
            typed_data_hash="0xa",
            expires_at=NOW,
        )
        two = Approval(
            id=new_id(),  # type: ignore[arg-type]
            intent_id=new_id(),  # type: ignore[arg-type]
            typed_data_hash="0xa",
            expires_at=NOW,
        )

        assert one != two


def an_intent_id_placeholder():
    from src.authority.domain.ids import IntentId

    return IntentId(new_id())


def invoice_amount():
    from tests.unit.authority._builders import usdc

    return usdc("25")
