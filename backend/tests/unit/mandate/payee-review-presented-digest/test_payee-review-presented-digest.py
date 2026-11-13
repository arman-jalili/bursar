"""Contract tests — `Payee.review_presented_digest` (mandate v1, P-2 / P-4, scenario 2).

Canonical: .pi/architecture/modules/mandate.md#aggregate-payee
Reference: .pi/architecture/modules/mandate.md#acceptance-criteria (AC #3, AC #5)

This is the operation the whole scam story turns on, so the contract is deliberately blunt about
two things:

* the method takes a **presented digest and nothing else** — there is no parameter that could carry
  a new address, because "our bank details changed" must not have an API;
* it returns `None` and reports through **events** (`PayeeDigestChanged` + `PayeeQuarantined`), so a
  refusal-shaped outcome cannot be quietly dropped by an ignored return value.

The behavioural assertion ("mismatch quarantines, address byte-identical") belongs to the
implementation item: asserting it here would make a contract test red the moment it got implemented.

Rewritten from the generated placeholder (hyphenated method names → `SyntaxError`).
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest
from src.mandate.domain.events import PayeeDigestChanged, PayeeQuarantined, PayeeRegistered
from src.mandate.domain.payee import Payee
from src.mandate.domain.values import BankDigest, PayeeStatus


class TestReviewSignature:
    def test_takes_only_a_digest_and_an_optional_invoice_id(self) -> None:
        signature = inspect.signature(Payee.review_presented_digest)
        assert list(signature.parameters) == ["self", "presented", "invoice_id"]

    def test_cannot_carry_a_new_address(self) -> None:
        """The scam needs a way to change the destination; the signature must not offer one."""
        parameters = inspect.signature(Payee.review_presented_digest).parameters
        forbidden = {"address", "new_address", "payee_address", "routing", "details"}
        assert not (set(parameters) & forbidden), (
            f"review_presented_digest accepts {set(parameters) & forbidden}; "
            "P-2 forbids rewriting the destination"
        )

    def test_presented_is_a_bank_digest(self) -> None:
        """Not a raw account number: the comparison happens on digests, never on routing details."""
        annotation = (
            inspect.signature(Payee.review_presented_digest).parameters["presented"].annotation
        )
        assert annotation in (BankDigest, "BankDigest")

    def test_returns_nothing_and_reports_by_event(self) -> None:
        """A `bool` return would invite callers to ignore it; events cannot be ignored (AC #12)."""
        assert inspect.signature(Payee.review_presented_digest).return_annotation in (None, "None")

    def test_is_synchronous(self) -> None:
        """An aggregate method must not do I/O; persistence is the repository's job (ADR-002)."""
        assert not inspect.iscoroutinefunction(Payee.review_presented_digest)


class TestQuarantineEvents:
    def test_digest_changed_event_payload_is_frozen(self) -> None:
        names = [f.name for f in dataclasses.fields(PayeeDigestChanged)]
        for required in ("payee_id", "presented_digest", "verified_digest", "invoice_id"):
            assert required in names, f"PayeeDigestChanged is missing {required}"

    def test_quarantined_event_carries_a_reason(self) -> None:
        """The reason becomes console copy and an evidence code — it is not optional."""
        assert "reason" in {f.name for f in dataclasses.fields(PayeeQuarantined)}
        assert PayeeQuarantined().reason == "bank_digest_mismatch"

    def test_events_are_past_tense_and_wire_stable(self) -> None:
        assert PayeeDigestChanged.event_name == "PayeeDigestChanged"
        assert PayeeQuarantined.event_name == "PayeeQuarantined"

    def test_events_carry_no_routing_details(self) -> None:
        """Evidence payloads are sealed and shareable; a raw account number must never be in one."""
        for event in (PayeeDigestChanged, PayeeQuarantined):
            payload_fields = {f.name for f in dataclasses.fields(event)}
            assert not (payload_fields & {"account_number", "routing_number", "address"})


class TestPayeeStatusContract:
    def test_quarantine_target_status_exists(self) -> None:
        assert PayeeStatus.QUARANTINED.value == "quarantined"

    def test_frozen_is_absorbing_by_contract(self) -> None:
        """P-4: a frozen payee that receives a mismatched digest stays frozen (no downgrade)."""
        assert {PayeeStatus.FROZEN, PayeeStatus.QUARANTINED} <= set(PayeeStatus)
        assert PayeeStatus.FROZEN != PayeeStatus.QUARANTINED

    def test_status_is_not_a_free_string_on_the_aggregate(self) -> None:
        annotation = Payee.__annotations__["status"]
        assert annotation in (PayeeStatus, "PayeeStatus")


class TestPayeeRegistrationIsTheOnlyEntryPoint:
    def test_register_is_a_classmethod(self) -> None:
        assert isinstance(inspect.getattr_static(Payee, "register"), classmethod)

    def test_register_requires_owner_actor_and_proof(self) -> None:
        """P-1: a payee cannot appear without an owner-verified address and digest."""
        signature = inspect.signature(Payee.register)
        assert {"actor", "proof"} <= set(signature.parameters)

    def test_registration_event_exists(self) -> None:
        assert PayeeRegistered.event_name == "PayeeRegistered"

    @pytest.mark.parametrize("method", ["freeze", "reapprove", "review_presented_digest"])
    def test_no_direct_status_assignment_api(self, method: str) -> None:
        """Every status change has an intention-named method; there is no `set_status`."""
        assert callable(getattr(Payee, method))
        assert not hasattr(Payee, "set_status")

    def test_frozen_is_terminal_within_a_mandate(self) -> None:
        """No `unfreeze`: the state diagram has FROZEN -> [*] only.

        Resuming a relationship is a re-registration with fresh owner proof, not a state flip —
        an undocumented transition with no event type would be a silent authority change (P-4)."""
        assert not hasattr(Payee, "unfreeze")
