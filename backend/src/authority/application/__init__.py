"""Authority application layer — the five catalog use cases (frozen).

Canonical: docs/architecture/modules/authority.md#application-services
Reference: docs/contracts/authority-contract-freeze.md §2

    EvaluateAuthority      FR-011   build the intent, re-read, decide, reserve
    ReserveCapacity        FR-013   the atomic hold
    EscalateForSignature   FR-014   bind a signature request to one intent
    SubmitOwnerSignature   FR-015   verify, consume, or refuse without side effect
    ReconcileReservation   FR-017   commit or release against the chain outcome

Names come from the exploration use-cases pass and are fixed. Each implementation opens exactly one
`session_scope` and appends drained events to `authority_outbox` in that transaction (ADR-003); no rule
lives in this layer.
"""
