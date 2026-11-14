"""Contract tests — `Payee.reapprove` (mandate v1, P-3 / P-5, AC #4).

Canonical: docs/architecture/modules/mandate.md#aggregate-payee
Reference: docs/architecture/decisions/ADR-005-authentication-authorization.md

The recovery path. Quarantine would be a dead end without it, and a dead end is not a feature — so
`reapprove` is part of the frozen contract, with three guarantees expressed in the signature:

* it takes an **owner `PartyRef` and an `OwnerSignatureProof`** — possession of a key is not enough
  to change a bank-detail baseline (P-3, P-5, ADR-005 layer 2);
* it takes the **new digest**, so the baseline replacement is explicit and auditable rather than a
  side effect of a generic save;
* it reports through `PayeeReapproved`, which carries **both** digests — evidence must show what
  changed, not merely that something did.

The failure behaviour ("invalid proof → `OwnerProofInvalid`, status unchanged") is asserted by the
implementation item.

Rewritten from the generated placeholder (hyphenated method names → `SyntaxError`).
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest
from src.mandate.domain.errors import MandateError, OwnerActionRequired, OwnerProofInvalid
from src.mandate.domain.events import PayeeReapproved
from src.mandate.domain.payee import Payee
from src.mandate.domain.values import BankDigest
from src.shared.domain.errors import ErrorCode


class TestReapproveSignature:
    def test_takes_new_digest_actor_and_proof(self) -> None:
        signature = inspect.signature(Payee.reapprove)
        assert list(signature.parameters) == ["self", "new_digest", "actor", "proof"]

    def test_requires_an_owner_actor(self) -> None:
        """P-3: clearing quarantine is an owner act. The actor is a parameter so it can be refused."""
        parameters = inspect.signature(Payee.reapprove).parameters
        assert "actor" in parameters
        assert parameters["actor"].annotation in (object, "PartyRef")

    def test_requires_a_proof_not_just_a_key(self) -> None:
        """ADR-005 layer 2: a stolen operator key must not be able to rebind a payee."""
        parameters = inspect.signature(Payee.reapprove).parameters
        assert "proof" in parameters

    def test_new_digest_is_a_bank_digest(self) -> None:
        annotation = inspect.signature(Payee.reapprove).parameters["new_digest"].annotation
        assert annotation in (BankDigest, "BankDigest")

    def test_returns_nothing(self) -> None:
        assert inspect.signature(Payee.reapprove).return_annotation in (None, "None")

    def test_actor_and_proof_are_keyword_only(self) -> None:
        """Swapping actor and proof positionally would invert "who" and "what proved it"."""
        parameters = inspect.signature(Payee.reapprove).parameters
        assert parameters["actor"].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters["proof"].kind is inspect.Parameter.KEYWORD_ONLY


class TestReapproveEvents:
    def test_reapproved_event_carries_both_digests(self) -> None:
        """Evidence must show what changed — "something changed" is not tamper evidence."""
        names = {f.name for f in dataclasses.fields(PayeeReapproved)}
        assert {"payee_id", "previous_digest", "new_digest", "actor_id"} <= names

    def test_event_name_is_wire_stable(self) -> None:
        assert PayeeReapproved.event_name == "PayeeReapproved"

    def test_event_carries_no_routing_details(self) -> None:
        payload_fields = {f.name for f in dataclasses.fields(PayeeReapproved)}
        assert not (payload_fields & {"account_number", "routing_number", "address"})

    def test_reapproved_event_does_not_claim_eligibility_directly(self) -> None:
        """The status transition is the aggregate's decision; the event only reports it happened."""
        payload_fields = {f.name for f in dataclasses.fields(PayeeReapproved)}
        assert "status" not in payload_fields


class TestOwnerRefusals:
    def test_owner_proof_invalid_is_a_wire_error(self) -> None:
        error = OwnerProofInvalid()
        assert isinstance(error, MandateError)
        assert error.code is ErrorCode.APPROVAL_INVALID
        assert error.http_status == 409
        assert error.retryable is False, (
            "re-signing requires the owner, not a retry of the same call"
        )

    def test_owner_action_required_is_a_forbidden_error(self) -> None:
        """An agent attempting this is 403, not 409: the credentials are fine, the actor is not."""
        error = OwnerActionRequired(role="agent")
        assert error.http_status == 403
        assert error.code is ErrorCode.FORBIDDEN
        assert error.details["role"] == "agent"

    def test_both_errors_are_distinguishable_programmatically(self) -> None:
        """Callers branch on type, not on message text."""
        assert not isinstance(OwnerActionRequired(role="agent"), OwnerProofInvalid)
        assert isinstance(OwnerProofInvalid(), MandateError)

    @pytest.mark.parametrize("error_cls", [OwnerProofInvalid, OwnerActionRequired])
    def test_error_message_is_presentable(self, error_cls: type) -> None:
        error = error_cls() if error_cls is OwnerProofInvalid else error_cls(role="agent")
        assert error.wire_message
        assert "Traceback" not in error.wire_message
