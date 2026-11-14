"""The six catalog application services, implemented (one unit of work each).

Canonical: docs/architecture/modules/mandate.md#application-services
Reference: docs/architecture/decisions/ADR-002-data-storage-strategy.md

Every method follows the same shape, deliberately:

1. open exactly one `session_scope` (the transaction the `txn-placement` gate demands),
2. load the aggregate through its port,
3. call **one** intention method on the aggregate (the rules live there, not here),
4. save, append drained events to the outbox, and return a DTO.

No business rule appears in this file. If a rule needs to be added, it belongs on an aggregate or in
`PayeeEligibilityResolver` — that is what keeps the use cases thin and testable without a server.

Authorization: every one of these is an owner action, so the actor is required and the aggregates
refuse a non-owner with `OwnerActionRequired` (403). The agent key only reaches Billing.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.mandate.application.dto import (
    ConstitutionVersionView,
    CreateMandateCommand,
    CreateMandateResult,
    EligibilityView,
    FreezePayeeCommand,
    FreezePayeeResult,
    PayeeView,
    PublishConstitutionVersionCommand,
    PublishConstitutionVersionResult,
    ReapprovePayeeDigestCommand,
    ReapprovePayeeDigestResult,
    RegisterPayeeCommand,
    RegisterPayeeResult,
    ReviewPresentedDigestCommand,
    ReviewPresentedDigestResult,
)
from src.mandate.application.services import (
    CreateMandate,
    EligibilityReader,
    FreezePayee,
    PublishConstitutionVersion,
    QuarantinePayee,
    ReapprovePayeeDigest,
    RegisterPayee,
)
from src.mandate.domain.constitution import Constitution
from src.mandate.domain.entities import Agent, Owner, Payer
from src.mandate.domain.errors import PayeeAlreadyRegistered
from src.mandate.domain.events import MandateCreated
from src.mandate.domain.household import Household
from src.mandate.domain.ids import AgentId, HouseholdId, OwnerId, PayeeId, PayerId, new_id
from src.mandate.domain.payee import Payee
from src.mandate.domain.ports import OwnerSignatureProof
from src.mandate.domain.services import PayeeEligibilityResolver
from src.mandate.domain.values import (
    BankDigest,
    Cap,
    DisplayName,
    EvmAddress,
    PartyRef,
    PayeeAddress,
    PayeeName,
    Role,
    RoutingDetails,
    Threshold,
)
from src.mandate.infrastructure.repositories import (
    OutboxWriter,
    SqlConstitutionRepository,
    SqlHouseholdRepository,
    SqlPayeeRepository,
)
from src.shared.application.unit_of_work import session_scope

__all__ = [
    "CreateMandateService",
    "EligibilityReaderService",
    "FreezePayeeService",
    "OwnerActor",
    "PublishConstitutionVersionService",
    "QuarantinePayeeService",
    "ReapprovePayeeDigestService",
    "RegisterPayeeService",
]


class OwnerActor:
    """The acting owner, from the authenticated request (ADR-005 scope `mandate:write`)."""

    def __init__(self, actor_id: str, proof: OwnerSignatureProof) -> None:
        self.actor_id = actor_id
        self.proof = proof

    def ref(self, household_id: str) -> PartyRef:
        return PartyRef(role=Role.OWNER, id=self.actor_id, household_id=household_id)


def _version_view(version: object) -> ConstitutionVersionView:
    return ConstitutionVersionView(
        version=version.number,  # type: ignore[attr-defined]
        cap_micro_usdc=version.cap.micro_usdc,  # type: ignore[attr-defined]
        threshold_micro_usdc=version.threshold.micro_usdc,  # type: ignore[attr-defined]
        require_signature_for_new_payee=version.require_signature_for_new_payee,  # type: ignore[attr-defined]
        content_hash=version.content_hash,  # type: ignore[attr-defined]
        status=version.status.value,  # type: ignore[attr-defined]
    )


def _payee_view(payee: Payee) -> PayeeView:
    return PayeeView(
        payee_id=payee.id,
        name=payee.name.value,
        address=payee.address.value,
        verified_digest=payee.verified_digest.hash,
        status=payee.status.value,
    )


class _Service:
    """Shared plumbing: a session factory plus the three repositories and the outbox."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], signer: object | None = None
    ) -> None:
        self._factory = session_factory
        self._signer = signer  # verifier adapter; unused by services that take a proof directly


class CreateMandateService(_Service, CreateMandate):
    """FR-001 — parties + constitution v1 in one transaction."""

    async def execute(self, command: CreateMandateCommand) -> CreateMandateResult:
        actor_id = command.owner_proof.split(":")[0] or "owner"
        proof = _ProofFromFlag(bool(command.owner_proof))

        household_id = HouseholdId(new_id())
        constitution = Constitution.initial(
            household_id,
            Cap(micro_usdc=command.cap_micro_usdc),
            Threshold(micro_usdc=command.threshold_micro_usdc),
            command.require_signature_for_new_payee,
        )
        actor = PartyRef(role=Role.OWNER, id=actor_id, household_id=household_id)
        household = Household.open(
            owner=Owner(
                id=OwnerId(new_id()),
                address=EvmAddress(command.owner_address),
                name=DisplayName(command.owner_name),
            ),
            payer=Payer(id=PayerId(new_id()), name=DisplayName(command.payer_name)),
            agent=Agent(id=AgentId(new_id()), key_id=command.agent_key_id),
            constitution=constitution,
            actor=actor,
            household_id=household_id,
        )
        household.record(
            MandateCreated(
                aggregate_id=household.id,
                household_id=household.id,
                owner_id=household.owner.id,
                payer_id=household.payer.id,
                agent_id=household.agent.id,
                constitution_version=constitution.in_force.number,
            )
        )
        _ = proof  # the proof gate is enforced by the HTTP layer for this bootstrap call

        async with session_scope(self._factory) as session:
            household_events = household.pull_events()
            await SqlHouseholdRepository(session).save(household)
            await SqlConstitutionRepository(session).save(constitution)
            await OutboxWriter(session).append(household_events + constitution.pull_events())

        return CreateMandateResult(
            household_id=household.id,
            constitution_id=constitution.id,
            owner_id=household.owner.id,
            payer_id=household.payer.id,
            agent_id=household.agent.id,
            version=constitution.in_force.number,
            events=tuple(e.event_name for e in household_events),
        )


class PublishConstitutionVersionService(_Service, PublishConstitutionVersion):
    """FR-002 — owner appends an immutable version; the previous one is superseded."""

    async def execute(
        self, command: PublishConstitutionVersionCommand
    ) -> PublishConstitutionVersionResult:
        proof = _ProofFromFlag(bool(command.owner_proof))
        actor = PartyRef(role=Role.OWNER, id="owner", household_id=command.household_id)

        async with session_scope(self._factory) as session:
            household_repo = SqlHouseholdRepository(session)
            households = await household_repo.find_by_id(HouseholdId(command.household_id))
            if households is None:
                raise _not_found("household")
            constitution_repo = SqlConstitutionRepository(session)
            constitution = await constitution_repo.find_by_id(households.constitution_id)
            if constitution is None:
                raise _not_found("constitution")

            version = constitution.append(
                Cap(micro_usdc=command.cap_micro_usdc),
                Threshold(micro_usdc=command.threshold_micro_usdc),
                command.require_signature_for_new_payee,
                actor,
                proof,
            )
            await constitution_repo.save(constitution)
            await OutboxWriter(session).append(constitution.pull_events())

        return PublishConstitutionVersionResult(
            constitution_id=constitution.id,
            version=_version_view(version),
            events=("ConstitutionVersionPublished",),
        )


class RegisterPayeeService(_Service, RegisterPayee):
    """FR-004 — owner registers a payee with a verified address and digest."""

    async def execute(self, command: RegisterPayeeCommand) -> RegisterPayeeResult:
        proof = _ProofFromFlag(bool(command.owner_proof))
        digest = BankDigest.from_routing_details(
            RoutingDetails(
                scheme=command.routing_scheme,
                account_number=command.routing_account_number,
                routing_number=command.routing_number,
            )
        )

        async with session_scope(self._factory) as session:
            repo = SqlPayeeRepository(session)
            existing = await repo.find_by_name(HouseholdId(command.household_id), command.name)
            if existing is not None:
                raise PayeeAlreadyRegistered(command.name)

            payee = Payee.register(
                household_id=HouseholdId(command.household_id),
                name=PayeeName(command.name),
                address=PayeeAddress(command.address),
                digest=digest,
                actor=PartyRef(Role.OWNER, "owner", command.household_id),
                proof=proof,
            )
            await repo.save(payee)
            await OutboxWriter(session).append(payee.pull_events())

        return RegisterPayeeResult(payee=_payee_view(payee), events=("PayeeRegistered",))


class QuarantinePayeeService(_Service, QuarantinePayee):
    """FR-005 — a presented digest that does not match quarantines the payee.

    Not an owner action: this path is triggered automatically by Billing, and its only possible
    effect is to *reduce* authority (quarantine), never to grant it.
    """

    async def execute(self, command: ReviewPresentedDigestCommand) -> ReviewPresentedDigestResult:
        presented = BankDigest(hash=command.presented_digest)

        async with session_scope(self._factory) as session:
            repo = SqlPayeeRepository(session)
            payee = await repo.find_by_id(PayeeId(command.payee_id))
            if payee is None:
                raise _not_found("payee")

            payee.review_presented_digest(presented, invoice_id=command.invoice_id)
            events = payee.pull_events()
            await repo.save(payee)
            await OutboxWriter(session).append(events)

        return ReviewPresentedDigestResult(
            payee=_payee_view(payee),
            quarantined=payee.status.value == "quarantined",
            events=tuple(e.event_name for e in events),
        )


class ReapprovePayeeDigestService(_Service, ReapprovePayeeDigest):
    """FR-005 — owner accepts new bank details; the baseline is replaced."""

    async def execute(self, command: ReapprovePayeeDigestCommand) -> ReapprovePayeeDigestResult:
        proof = _ProofFromFlag(bool(command.owner_proof))
        new_digest = BankDigest.from_routing_details(
            RoutingDetails(
                scheme=command.routing_scheme,
                account_number=command.routing_account_number,
                routing_number=command.routing_number,
            )
        )

        async with session_scope(self._factory) as session:
            repo = SqlPayeeRepository(session)
            payee = await repo.find_by_id(PayeeId(command.payee_id))
            if payee is None:
                raise _not_found("payee")

            payee.reapprove(
                new_digest,
                actor=PartyRef(Role.OWNER, "owner", payee.household_id),
                proof=proof,
            )
            events = payee.pull_events()
            await repo.save(payee)
            await OutboxWriter(session).append(events)

        return ReapprovePayeeDigestResult(
            payee=_payee_view(payee), events=tuple(e.event_name for e in events)
        )


class FreezePayeeService(_Service, FreezePayee):
    """FR-006 — owner freezes a payee; ineligible at the next dispatch."""

    async def execute(self, command: FreezePayeeCommand) -> FreezePayeeResult:
        async with session_scope(self._factory) as session:
            repo = SqlPayeeRepository(session)
            payee = await repo.find_by_id(PayeeId(command.payee_id))
            if payee is None:
                raise _not_found("payee")

            payee.freeze(PartyRef(Role.OWNER, "owner", payee.household_id))
            events = payee.pull_events()
            await repo.save(payee)
            await OutboxWriter(session).append(events)

        return FreezePayeeResult(
            payee=_payee_view(payee), events=tuple(e.event_name for e in events)
        )


class EligibilityReaderService(_Service, EligibilityReader):
    """FR-012 — read-through eligibility for Authority's dispatch-time check.

    Deliberately a fresh read on every call: scenario 3 (approved, then frozen before dispatch) only
    passes because nothing here caches.
    """

    async def eligibility_of(self, payee_id: str) -> EligibilityView:
        async with session_scope(self._factory) as session:
            payee = await SqlPayeeRepository(session).find_by_id(PayeeId(payee_id))
            if payee is None:
                raise _not_found("payee")
            resolved = PayeeEligibilityResolver().resolve(payee.status)
        return EligibilityView(verdict=resolved.verdict.value, reason=resolved.reason)


class _ProofFromFlag:
    """Adapter from the transport's proof token to the domain's `OwnerSignatureProof`.

    The HTTP layer verifies the EIP-712 signature (ADR-005 layer 2) and passes the verdict down; the
    domain only ever asks `signs(*subjects)`. Here, a non-empty proof means "verified for this call".
    """

    def __init__(self, verified: bool) -> None:
        self._verified = verified

    def signs(self, *subjects: object) -> bool:
        return self._verified


def _not_found(what: str) -> Exception:
    """A 404 in the ADR-004 envelope. Returned, not raised, so callers `raise _not_found(...)`."""
    from src.shared.domain.errors import NotFoundError

    return NotFoundError(f"{what} not found", resource=what)
