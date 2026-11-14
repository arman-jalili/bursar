"""Contract tests — Mandate domain services and ports (v1).

Canonical: docs/architecture/modules/mandate.md#components
Reference: docs/architecture/decisions/ADR-005-authentication-authorization.md

Two ports are frozen here, and each exists to keep a decision out of an aggregate:

`EligibilityResolver` — combines payee status with the constitution flag
(`require_signature_for_new_payee`). It spans two aggregates, so it is a domain service, and its
output is the `Eligibility` value object Authority acts on at dispatch (FR-012).

`OwnerSignatureProof` — the aggregate must be able to ask "is this change owner-authorized?" without
knowing how EIP-712 verification works. Proof arrives as an *argument*, which is what makes
"who authorized this" un-forgeable: there is no flag to set instead.

Behaviour (the actual status→verdict mapping) is the `domain-services` implementation item's job;
what is frozen now is that the mapping lives behind this interface and yields `Eligibility`.

Rewritten from the generated placeholder (hyphenated method names → `SyntaxError`).
"""

from __future__ import annotations

import inspect
from typing import runtime_checkable

import pytest
from src.mandate.domain.ports import EligibilityResolver, OwnerSignatureProof
from src.mandate.domain.values import (
    Eligibility,
    EligibilityVerdict,
    PayeeStatus,
    ReasonCode,
)


class TestEligibilityResolverContract:
    def test_is_an_abstract_domain_service(self) -> None:
        assert inspect.isabstract(EligibilityResolver)

    def test_exposes_resolve_with_status_and_flag(self) -> None:
        """The flag is the constitution's input; omitting it would duplicate policy in the resolver."""
        signature = inspect.signature(EligibilityResolver.resolve)
        assert list(signature.parameters) == [
            "self",
            "status",
            "require_signature_for_new_payee",
        ]
        assert signature.parameters["status"].annotation in (PayeeStatus, "PayeeStatus")

    def test_returns_an_eligibility_value_object(self) -> None:
        assert inspect.signature(EligibilityResolver.resolve).return_annotation in (
            Eligibility,
            "Eligibility",
        )

    def test_coverable_statuses_are_the_closed_set(self) -> None:
        """Every status must have a verdict; a status with no verdict is a bug, not a default."""
        assert set(PayeeStatus) == {
            PayeeStatus.NEW,
            PayeeStatus.ELIGIBLE,
            PayeeStatus.QUARANTINED,
            PayeeStatus.FROZEN,
        }


class TestOwnerSignatureProofContract:
    def test_is_a_runtime_checkable_protocol(self) -> None:
        assert getattr(OwnerSignatureProof, "_is_protocol", False) is True
        assert isinstance(OwnerSignatureProof, type)
        assert runtime_checkable(OwnerSignatureProof) is not None

    def test_signs_is_variadic(self) -> None:
        """Three different changes are signed: H-5 (cap/threshold), P-1 (digest/address),
        P-5 (payee_id/new_digest). A fixed arity would force three ports."""
        signature = inspect.signature(OwnerSignatureProof.signs)
        kinds = [p.kind for p in signature.parameters.values()]
        assert inspect.Parameter.VAR_POSITIONAL in kinds

    def test_signs_returns_bool(self) -> None:
        assert inspect.signature(OwnerSignatureProof.signs).return_annotation in (bool, "bool")

    def test_a_duck_typed_verifier_satisfies_the_protocol(self) -> None:
        """Adapters implement this without inheriting — the domain never sees their type."""

        class FakeProof:
            def __init__(self, ok: bool) -> None:
                self._ok = ok

            def signs(self, *subjects: object) -> bool:
                return self._ok

        assert isinstance(FakeProof(True), OwnerSignatureProof)

    def test_proof_is_not_storable_on_an_aggregate(self) -> None:
        """Proof is an argument, not state — otherwise an approval could be reused (A-14 in Authority)."""
        for module_name in ("payee", "constitution", "household"):
            module = __import__(f"src.mandate.domain.{module_name}", fromlist=["*"])
            for name, obj in inspect.getmembers(module, inspect.isclass):
                annotations = getattr(obj, "__annotations__", {})
                assert "proof" not in annotations, (
                    f"{name} stores an owner proof as state; it must be passed per-call"
                )


class TestEligibilityOutputShape:
    def test_verdicts_authority_can_act_on(self) -> None:
        assert {v.value for v in EligibilityVerdict} == {"allow", "escalate", "deny"}

    def test_reason_code_vocabulary_is_lowercase_and_closed(self) -> None:
        """Domain reason codes are data (sealed into evidence), not HTTP details."""
        assert {c.value for c in ReasonCode} == {
            "new_payee",
            "digest_mismatch",
            "payee_quarantined",
            "payee_frozen",
            "cap_exceeded",
            "duplicate_invoice",
            "approval_invalid",
            "amount_mismatch",
            "budget_exhausted",
        }

    def test_every_refusal_reason_has_a_matching_wire_error_code(self) -> None:
        """ADR-004 envelope and the evidence payload must name the same failure the same way.

        Lowercase domain code ↔ uppercase wire code. Drift here means the console translates one
        code and the verifier asserts on another.
        """
        from src.shared.domain.errors import ErrorCode

        refusals = [c for c in ReasonCode if not c.is_escalation]
        unmapped = [c.value for c in refusals if c.value.upper() not in ErrorCode.__members__]
        assert unmapped == [], f"reason codes with no wire ErrorCode: {unmapped}"

    def test_escalation_reason_is_not_a_wire_error(self) -> None:
        """`new_payee` is not a failure — it must never appear as an HTTP error code."""
        from src.shared.domain.errors import ErrorCode

        assert ReasonCode.NEW_PAYEE.is_escalation
        assert "NEW_PAYEE" not in ErrorCode.__members__

    def test_deny_and_escalate_require_a_reason(self) -> None:
        with pytest.raises(ValueError, match="requires a reason"):
            Eligibility(verdict=EligibilityVerdict.DENY)
        with pytest.raises(ValueError, match="requires a reason"):
            Eligibility(verdict=EligibilityVerdict.ESCALATE)
        assert Eligibility(verdict=EligibilityVerdict.ALLOW).reason is None
