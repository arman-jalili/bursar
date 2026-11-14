"""Evidence domain — framework-free, persistence-ignorant (frozen).

Canonical: docs/architecture/modules/evidence.md#components
Reference: docs/contracts/evidence-contract-freeze.md §2

Service-depth context (ADR-008): the four captured types are the whole model — `EvidenceEnvelope`,
`Anchor`, `EnvelopeHash` and `VerificationResult` — plus the verification outcome record required to
name a failing field. There are no extra aggregates and no extra domain events.

Every function body raises `NotImplementedError("E-n — see module doc")` until Phase B. The suffix is
the invariant the body must satisfy, not decoration: it is what the failing tests point at.
"""
