"""The six catalog application services of the Mandate context — frozen interfaces (v1).

Canonical: .pi/architecture/modules/mandate.md#application-services
Reference: .pi/architecture/decisions/ADR-003-cross-context-communication.md

Names and FR mappings are authoritative: they come from the exploration use-cases pass
(`.pi/domain/exploration/*.raw.json`) and an implementation item may not rename, drop or substitute
them.

    CreateMandate                FR-001
    PublishConstitutionVersion   FR-002
    RegisterPayee                FR-004
    QuarantinePayee              FR-005   (triggered by a presented digest)
    ReapprovePayeeDigest         FR-005
    FreezePayee                  FR-006

Each method is `async` and takes/returns DTOs, never aggregates: the caller cannot reach into
`Household` because it never receives one. Every implementation must open exactly one
`session_scope` and append the aggregate's events to `mandate_outbox` in that transaction (AC #12).

Not routed through the agent: every one of these is an owner action. The agent's key holds
`billing:propose` only, so authorization fails before an aggregate is loaded (ADR-005, AC #9).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.mandate.application.dto import (
    CreateMandateCommand,
    CreateMandateResult,
    EligibilityView,
    FreezePayeeCommand,
    FreezePayeeResult,
    PublishConstitutionVersionCommand,
    PublishConstitutionVersionResult,
    ReapprovePayeeDigestCommand,
    ReapprovePayeeDigestResult,
    RegisterPayeeCommand,
    RegisterPayeeResult,
    ReviewPresentedDigestCommand,
    ReviewPresentedDigestResult,
)

__all__ = [
    "CreateMandate",
    "EligibilityReader",
    "FreezePayee",
    "PublishConstitutionVersion",
    "QuarantinePayee",
    "ReapprovePayeeDigest",
    "RegisterPayee",
]


class CreateMandate(ABC):
    """Owner establishes the household mandate (FR-001)."""

    @abstractmethod
    async def execute(self, command: CreateMandateCommand) -> CreateMandateResult:
        raise NotImplementedError


class PublishConstitutionVersion(ABC):
    """Owner appends an immutable constitution version; the previous one is superseded (FR-002)."""

    @abstractmethod
    async def execute(
        self, command: PublishConstitutionVersionCommand
    ) -> PublishConstitutionVersionResult:
        raise NotImplementedError


class RegisterPayee(ABC):
    """Owner registers a payee with a verified address and digest, as `NEW` (FR-004)."""

    @abstractmethod
    async def execute(self, command: RegisterPayeeCommand) -> RegisterPayeeResult:
        raise NotImplementedError


class QuarantinePayee(ABC):
    """React to a bank-digest mismatch by suspending the payee until the owner re-approves (FR-005).

    Named for its effect, not its cause: the trigger is a presented digest, the consequence is
    quarantine. There is no "update bank details" service — that operation does not exist (P-2).
    """

    @abstractmethod
    async def execute(self, command: ReviewPresentedDigestCommand) -> ReviewPresentedDigestResult:
        raise NotImplementedError


class ReapprovePayeeDigest(ABC):
    """Owner accepts new bank details; the baseline is replaced and the payee returns to eligible
    (FR-005)."""

    @abstractmethod
    async def execute(self, command: ReapprovePayeeDigestCommand) -> ReapprovePayeeDigestResult:
        raise NotImplementedError


class FreezePayee(ABC):
    """Owner freezes a payee so it is ineligible at the next dispatch (FR-006)."""

    @abstractmethod
    async def execute(self, command: FreezePayeeCommand) -> FreezePayeeResult:
        raise NotImplementedError


class EligibilityReader(ABC):
    """Read-through eligibility query consumed by Authority at dispatch (FR-012, AC #11).

    Its own interface, and its own call, because a cached answer is exactly the bug scenario 3
    exists to catch: the payee was eligible when planned and frozen before dispatch.
    """

    @abstractmethod
    async def eligibility_of(self, payee_id: str) -> EligibilityView:
        raise NotImplementedError
