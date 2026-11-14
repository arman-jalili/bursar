"""Mandate application layer — use-case orchestration, DTOs and service contracts.

Canonical: docs/architecture/modules/mandate.md#application-services
Reference: docs/architecture/decisions/ADR-002-data-storage-strategy.md

Frozen contract v1:

    dto.py       request/result DTOs — the shape of every input and output (AC #3)
    services.py  one ABC per catalog application service (6 total, names fixed by the
                 exploration use-cases pass)

Rules this layer owns, and the domain does not:

* **One application service = one unit of work = one transaction** (`session_scope`), with the
  aggregate's events written to `mandate_outbox` in that same transaction (ADR-003, AC #12).
* Authorization by scope (ADR-005): the agent key is rejected here, before any aggregate is loaded.
* Translation between DTOs and domain types. The domain never sees a DTO.

Bodies are TODO: the application-services item fills them in; the signatures are frozen so the
HTTP and persistence items can be written against them in parallel.
"""
