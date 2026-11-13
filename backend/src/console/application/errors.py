"""The console's refusal vocabulary — presentation refusals, not domain errors.

Canonical: .pi/architecture/modules/console.md#components
Reference: docs/contracts/console-contract-freeze.md §2.4

There is no domain layer (CON-09), so these are the errors the console itself raises when an
invariant would be violated while projecting or proxying. The HTTP layer maps them onto the shared
error envelope (ADR-004); no caller should have to parse a message string.

Naming note: the ubiquitous language is `violation`/`refusal`, not `...Error` — a row here is an
asserted rule, and `WhitelistViolation` reads as the rule it defends.
"""

from __future__ import annotations

__all__ = [
    "ConsoleRefusal",
    "DomainLayerPresent",
    "FieldFidelityViolation",
    "PayerVocabularyViolation",
    "PayoutNotLabelled",
    "ReadOnlyViolation",
    "RefusalReasonMissing",
    "SignatureRewritten",
    "UnknownReasonCode",
    "VerificationRefused",
    "ViewportContractViolation",
    "WhitelistViolation",
]


class ConsoleRefusal(Exception):
    """Base for every console refusal. A caller can catch one type and trust it is a contract breach."""


class WhitelistViolation(ConsoleRefusal):
    """CON-01 — a payload carried a key no surface whitelist names."""


class FieldFidelityViolation(ConsoleRefusal):
    """CON-02 — a field was normalised, truncated or re-rendered on its way to a surface."""


class SignatureRewritten(ConsoleRefusal):
    """CON-03 — the signature body was parsed, re-ordered or re-encoded before forwarding."""


class ReadOnlyViolation(ConsoleRefusal):
    """CON-04 — the console attempted a write other than the signature passthrough."""


class PayerVocabularyViolation(ConsoleRefusal):
    """CON-05 — payer copy contained crypto vocabulary (NFR-017)."""


class PayoutNotLabelled(ConsoleRefusal):
    """CON-06 — a settled bill reached the payer surface without the simulated-payout label."""


class RefusalReasonMissing(ConsoleRefusal):
    """CON-07 — a refusal was rendered with no reason code to translate."""


class UnknownReasonCode(ConsoleRefusal):
    """CON-07 — a reason code arrived that the frozen copy table does not know."""


class VerificationRefused(ConsoleRefusal):
    """CON-08 — Evidence could not return a verdict; the console must not invent one."""


class DomainLayerPresent(ConsoleRefusal):
    """CON-09 — `src/console/domain/` exists, which is an architecture violation, not a refactor."""


class ViewportContractViolation(ConsoleRefusal):
    """CON-10 — a surface is not usable at the frozen mobile viewport."""
