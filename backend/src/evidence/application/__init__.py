"""Evidence application layer — use cases, DTOs and the unit-of-work boundary.

Canonical: .pi/architecture/modules/evidence.md#application-services
Reference: docs/contracts/evidence-contract-freeze.md §2.7

Phase A: signatures only. `SealEvidence` and `VerifyEvidence` are dataclasses whose `execute` raises
`NotImplementedError("E-n — see module doc")`.

What the implementations will own (and the domain will not): exactly one `claim` + `append` + anchor
attempt per delivery, the outbox append in the same transaction, and the witness-only decision that a
signing/anchoring failure is recorded as a gap rather than propagated to the publisher (E-10).
"""
