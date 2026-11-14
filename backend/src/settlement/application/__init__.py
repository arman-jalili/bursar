"""Settlement application layer — use cases, DTOs, and the unit-of-work boundary (frozen).

Canonical: docs/architecture/modules/settlement.md#application-services
Reference: docs/contracts/settlement-contract-freeze.md §2.9

Phase A: signatures only. The six catalog services are ABCs whose `execute` raises
`NotImplementedError("SC-n — see module doc")`.

What the implementations will own (and the domain will not): exactly one `session_scope` per use case,
the write-ahead ordering (persist hash → broadcast), the outbox append in that same transaction, and
the refusal mapping that turns a spent nullifier or a chain revert into a recorded outcome rather than
a retry.
"""
