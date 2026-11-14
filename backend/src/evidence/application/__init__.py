"""Evidence application layer — use cases, DTOs and concrete composition wrappers.

Canonical: .pi/architecture/modules/evidence.md#application-services
Reference: docs/contracts/evidence-contract-freeze.md §2.7

`services.py` holds the two catalog use cases (`SealEvidence`, `VerifyEvidence`) plus the
`WitnessReport` read model, written against ports only. `services_impl.py` gives them a session and
adapters for the runtime; it is the only application file that names infrastructure.

The application layer owns exactly one transaction per call (ADR-002): one `claim` + `append` per
delivery, an anchor attempt in the same unit of work, and the witness-only decision that a
signing/anchoring failure is a reported gap rather than a publisher error (E-10).
"""
