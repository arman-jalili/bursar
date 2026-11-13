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

Bodies are TODO: the `aggregate-constitution` implementation item fills them in.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from src.mandate.domain.errors import ThresholdExceedsCap  # noqa: F401  (documented, raised later)
from src.mandate.domain.ids import ConstitutionId, HouseholdId
from src.mandate.domain.ports import OwnerSignatureProof
from src.mandate.domain.values import Cap, PartyRef, Threshold
from src.shared.domain.aggregate import AggregateRoot
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
        raise NotImplementedError("ConstitutionVersion.supersede — see module doc AC #7")

    def next_version(
        self,
        cap: Cap,
        threshold: Threshold,
        require_signature_for_new_payee: bool,
    ) -> ConstitutionVersion:
        """Build version n+1 (contiguous numbering, fresh content hash) — H-8."""
        raise NotImplementedError("ConstitutionVersion.next_version — see module doc AC #7")


@dataclass(eq=False)
class Constitution(AggregateRoot):
    """The append-only lineage. Publishing supersedes; it never mutates history."""

    id: ConstitutionId
    household_id: HouseholdId
    _versions: list[ConstitutionVersion] = field(default_factory=list)

    @classmethod
    def initial(cls, household_id: HouseholdId, cap: Cap, threshold: Threshold) -> Constitution:
        """v1 of a brand-new household (called by `CreateMandate`)."""
        raise NotImplementedError("Constitution.initial — see module doc AC #7")

    @property
    def in_force(self) -> ConstitutionVersion:
        """The single binding version.

        Raises:
            ConstitutionCorrupted: when 0 or 2+ versions are live (H-4, AC #8).

        Read-through contract: callers must not cache this (FR-012).
        """
        raise NotImplementedError("Constitution.in_force — see module doc AC #8")

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
        raise NotImplementedError("Constitution.append — see module doc AC #7")

    def find_version(self, number: int) -> ConstitutionVersion:
        """Historical lookup by number — AC #7 ("old version still readable").

        Named `find_version`, not `version`: `AggregateRoot.version` is the optimistic-concurrency
        counter (ADR-002), and a method of the same name would shadow it — mypy caught the override
        during the contract freeze. Same name as `ConstitutionRepository.find_version`, so the port
        and the aggregate are symmetrical.
        """
        raise NotImplementedError("Constitution.find_version — see module doc AC #7")

    def versions(self) -> tuple[ConstitutionVersion, ...]:
        """The whole lineage, oldest first. Read-only view; no mutation surface."""
        raise NotImplementedError("Constitution.versions — see module doc AC #7")


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
