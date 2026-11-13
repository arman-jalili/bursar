"""Constitution — append-only lineage of immutable rule sets.

Canonical: .pi/architecture/modules/mandate.md#aggregate-constitution
Reference: .pi/architecture/decisions/ADR-007-compliance-engine-architecture.md

Contract (v1) — aggregate root `Constitution`, entity `ConstitutionVersion`:

    H-4  exactly one version is IN_FORCE per household
    H-5  appending requires an owner signature over the new cap/threshold
    H-6  threshold <= cap, both positive
    H-7  a published version is immutable; status may only move IN_FORCE -> SUPERSEDED
    H-8  version numbers are contiguous from 1; content_hash matches content

Why `ConstitutionVersion` is an entity and not a value object: versions are addressed by
`(constitution_id, number)` in `ConstitutionRepository.find_version`, and a past determination cites
one by number. Two "version 3"s in different constitutions are different records; two versions with
identical rules are still two versions because history is positional. Identity persists, state
(`status`) changes once, and it can never change again.

Why there is no setter anywhere: "a published version is immutable" is only true if the type makes
mutation unrepresentable. `supersede()` is the single, one-way transition.

Supersession is a state flip on a frozen-content version; nothing here can rewrite history.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field

from src.mandate.domain.errors import (
    ConstitutionCorrupted,
    OwnerActionRequired,
    OwnerProofInvalid,
    ThresholdExceedsCap,
)
from src.mandate.domain.events import CapChanged, ConstitutionVersionPublished, ThresholdChanged
from src.mandate.domain.ids import ConstitutionId, HouseholdId, new_id
from src.mandate.domain.ports import OwnerSignatureProof
from src.mandate.domain.values import Cap, PartyRef, Role, Threshold
from src.shared.domain.aggregate import AggregateRoot
from src.shared.domain.event import utcnow
from src.shared.domain.value_object import ValueObject

__all__ = ["Constitution", "ConstitutionVersion", "VersionStatus"]


class VersionStatus(enum.StrEnum):
    """The only two states a published version may be in (H-7)."""

    IN_FORCE = "in_force"
    SUPERSEDED = "superseded"


@dataclass(eq=False)
class ConstitutionVersion:
    """An immutable snapshot of the rules that were in force at some point (H-5…H-8).

    Frozen contract: fields are exactly what the enforcement engine reads at dispatch (ADR-007,
    Lock 2) plus the audit metadata a past refusal needs to cite.
    """

    number: int
    cap: Cap
    threshold: Threshold
    require_signature_for_new_payee: bool
    content_hash: str
    status: VersionStatus = VersionStatus.IN_FORCE

    def supersede(self) -> None:
        """One-way transition IN_FORCE -> SUPERSEDED. Calling twice must raise (H-7)."""
        if self.status is not VersionStatus.IN_FORCE:
            raise ConstitutionCorrupted(0)  # superseding a superseded version rewrites history
        self.status = VersionStatus.SUPERSEDED

    def next_version(
        self,
        cap: Cap,
        threshold: Threshold,
        require_signature_for_new_payee: bool,
    ) -> ConstitutionVersion:
        """Build version n+1 (contiguous numbering, fresh content hash) — H-8."""
        return ConstitutionVersion(
            number=self.number + 1,
            cap=cap,
            threshold=threshold,
            require_signature_for_new_payee=require_signature_for_new_payee,
            content_hash=_content_hash(
                self.number + 1, cap, threshold, require_signature_for_new_payee
            ),
        )


@dataclass(eq=False)
class Constitution(AggregateRoot):
    """The append-only lineage. Publishing supersedes; it never mutates history."""

    id: ConstitutionId
    household_id: HouseholdId
    _versions: list[ConstitutionVersion] = field(default_factory=list)

    @classmethod
    def initial(
        cls,
        household_id: HouseholdId,
        cap: Cap,
        threshold: Threshold,
        require_signature_for_new_payee: bool = True,
    ) -> Constitution:
        """v1 of a brand-new household (called by `CreateMandate`)."""
        if threshold.micro_usdc > cap.micro_usdc:
            raise ThresholdExceedsCap(str(threshold.micro_usdc), str(cap.micro_usdc))
        constitution = cls(id=ConstitutionId(new_id()), household_id=household_id)
        constitution._versions.append(
            ConstitutionVersion(
                number=1,
                cap=cap,
                threshold=threshold,
                require_signature_for_new_payee=require_signature_for_new_payee,
                content_hash=_content_hash(1, cap, threshold, require_signature_for_new_payee),
            )
        )
        return constitution

    @property
    def in_force(self) -> ConstitutionVersion:
        """The single binding version.

        Raises:
            ConstitutionCorrupted: when 0 or 2+ versions are live (H-4, AC #8).

        Read-through contract: callers must not cache this (FR-012).
        """
        live = [v for v in self._versions if v.status is VersionStatus.IN_FORCE]
        if len(live) != 1:
            raise ConstitutionCorrupted(len(live))
        return live[0]

    def append(
        self,
        cap: Cap,
        threshold: Threshold,
        require_signature_for_new_payee: bool,
        actor: PartyRef,
        proof: OwnerSignatureProof,
    ) -> ConstitutionVersion:
        """Supersede the in-force version and return the new one (AC #7).

        Raises:
            OwnerActionRequired: non-owner actor (H-3).
            OwnerProofInvalid: signature does not cover (household, cap, threshold) (H-5).
            ThresholdExceedsCap: threshold > cap (H-6).
        """
        if actor.role is not Role.OWNER:
            raise OwnerActionRequired(role=actor.role.value)
        if not proof.signs(self.household_id, cap, threshold):
            raise OwnerProofInvalid("the owner signature does not cover this cap and threshold")
        if threshold.micro_usdc > cap.micro_usdc:
            raise ThresholdExceedsCap(str(threshold.micro_usdc), str(cap.micro_usdc))

        previous = self.in_force
        if (
            previous.cap == cap
            and previous.threshold == threshold
            and previous.require_signature_for_new_payee == require_signature_for_new_payee
        ):
            raise OwnerProofInvalid("that version is already in force; nothing to publish")

        next_version = previous.next_version(cap, threshold, require_signature_for_new_payee)
        previous.supersede()
        self._versions.append(next_version)
        self.record(
            ConstitutionVersionPublished(
                aggregate_id=self.id,
                constitution_id=self.id,
                version=next_version.number,
                content_hash=next_version.content_hash,
                cap_micro_usdc=cap.micro_usdc,
                threshold_micro_usdc=threshold.micro_usdc,
                published_at_iso=utcnow().isoformat(),
            )
        )
        if previous.cap != cap:
            self.record(
                CapChanged(
                    aggregate_id=self.id,
                    household_id=self.household_id,
                    version=next_version.number,
                    from_micro_usdc=previous.cap.micro_usdc,
                    to_micro_usdc=cap.micro_usdc,
                )
            )
        if previous.threshold != threshold:
            self.record(
                ThresholdChanged(
                    aggregate_id=self.id,
                    household_id=self.household_id,
                    version=next_version.number,
                    from_micro_usdc=previous.threshold.micro_usdc,
                    to_micro_usdc=threshold.micro_usdc,
                )
            )
        return next_version

    def find_version(self, number: int) -> ConstitutionVersion:
        """Historical lookup by number — AC #7 ("old version still readable").

        Named `find_version`, not `version`: `AggregateRoot.version` is the optimistic-concurrency
        counter (ADR-002), and a method of the same name would shadow it — mypy caught the override
        during the contract freeze. Same name as `ConstitutionRepository.find_version`, so the port
        and the aggregate are symmetrical.
        """
        for version in self._versions:
            if version.number == number:
                return version
        raise KeyError(f"constitution {self.id} has no version {number}")

    def versions(self) -> tuple[ConstitutionVersion, ...]:
        """The whole lineage, oldest first. Read-only view; no mutation surface."""
        return tuple(sorted(self._versions, key=lambda v: v.number))

    def policy(self) -> ConstitutionPolicy:
        """The in-force rules, detached from history — what a determination quotes (A-6)."""
        live = self.in_force
        return ConstitutionPolicy(
            version_number=live.number,
            cap=live.cap,
            threshold=live.threshold,
            require_signature_for_new_payee=live.require_signature_for_new_payee,
        )


@dataclass(frozen=True, slots=True)
class ConstitutionPolicy(ValueObject):
    """The subset of a version that the enforcement engine needs, detached from history.

    Exists so Authority can hold "the rules I was judged against" without holding a live aggregate
    reference. Frozen: a determination must be able to quote the exact rules it used (A-6).
    """

    version_number: int
    cap: Cap
    threshold: Threshold
    require_signature_for_new_payee: bool


def _content_hash(version: int, cap: Cap, threshold: Threshold, require_signature: bool) -> str:
    """Stable hash of a version's content, so tampering with a stored version is detectable (H-8)."""
    canonical = json.dumps(
        {
            "version": version,
            "cap_micro_usdc": cap.micro_usdc,
            "threshold_micro_usdc": threshold.micro_usdc,
            "require_signature_for_new_payee": require_signature,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
