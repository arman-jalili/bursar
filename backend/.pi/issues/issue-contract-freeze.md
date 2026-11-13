---
guardian_issue:
  id: "ISSUE-CONTRACT-FREEZE"
  epic: "billing"
  component: "Contract Freeze"
  module: "billing"
  status: planned
  priority: critical
  dependencies: []

  in_scope:
    - Define public interfaces for all components in this epic
    - Define DTOs, schemas, and API contracts
    - Document event payloads and topics
    - Create interface stubs with no implementation
    - Freeze: no implementation changes without contract change

  out_of_scope:
    - Any implementation logic
    - Database schema changes
    - Infrastructure setup

  affected_layers:
    domain:
      - Interface definitions for domain services
    application:
      - Input/output DTO definitions
    api:
      - REST/event contracts

  canonical_references:
    - module: ".pi/architecture/modules/billing.md"

  acceptance_criteria:
    - "All component interfaces defined as stubs (TODO bodies)"
    - "DTO schemas documented with field names and types"
    - "API contracts frozen and reviewed"
    - "Implementation PRs reference these contracts"

  validators:
    - architecture
    - canonical

  implementation_notes: |
    Define the contract before any implementation. Every implementation issue
    depends on this contract being frozen first. The contract should include:
    interfaces, types, DTOs, event schemas, API paths, error formats.

  file_changes:
    - "create: src/billing/domain/"
    - "create: src/billing/application/"
    - "create: src/billing/infrastructure/"
    - "create: src/billing/interfaces/"
---

# Contract Freeze: billing

## Intent

Define and freeze all public interfaces, contracts, and schemas for the billing
epic before any implementation begins. This prevents architecture drift — implementation
must satisfy contracts, not the other way around.

## Included Components

- Persistence contract
- Ports
- `InvoiceHash`
- Duplicate invoice
- At most one attempt
- Forbidden fields
- Settled invoice
- Digest review
- Refusal path
- Layer purity

## What Must Be Frozen

### Interfaces
- Service interfaces for every component
- Repository/DAO interfaces
- Factory interfaces

### Contracts
- Input/output DTO schemas
- API endpoint contracts (method, path, request/response)
- Event payload schemas
- Error response formats

### Out of Bounds (no contracts needed)
- Internal implementation details
- Database column names (hidden behind repository)
- Framework-specific annotations

## Acceptance Criteria

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | All component interfaces defined as stubs (TODO bodies) | Check src/<module>/domain/ and application/ |
| 2 | Contracts reviewed and frozen | PR approval |
| 3 | DTO schemas documented with field names and types | OpenAPI / record types |
| 4 | Implementation depends on contracts | No implementation without interface |

## Full Module Acceptance Criteria (for reference)

> These are the complete ACs for the module. The contract freeze must define the interfaces
> so every row below can be implemented in subsequent issues.

| # | Component | Criterion | Verify In |
|---|-----------|-----------|-----------|
| 1 | `InvoiceHash` | Same document → same hash; one changed character → different hash. | unit |
| 2 | Duplicate invoice | Recording the same hash twice yields the original invoice + `DuplicateInvoiceDetected`, no second row. | integration |
| 3 | At most one attempt | Two concurrent proposals for one invoice → exactly one `PaymentAttempt`; second gets `InvoiceNotPayable`. | integration (concurrency) |
| 4 | Forbidden fields | Proposal with `payee_address`, `command`, `cap` or `threshold` → 422 `PROPOSAL_REJECTED`, zero attempts persisted. | integration |
| 5 | Settled invoice | Proposal against a settled invoice → refused; no attempt row. (scenario 6, app layer) | integration |
| 6 | Digest review | An invoice whose presented digest ≠ Mandate's verified digest triggers Mandate quarantine and the attempt is refused downstream. (scenario 2) | integration |
| 7 | Refusal path | A denied determination sets the attempt `REFUSED` and the invoice back to outstanding, with no reservation committed. | integration |
| 8 | Layer purity | `src/billing/domain/` imports no FastAPI/SQLAlchemy/httpx. | automated |

## Full Implementation Sequence (for reference)

- 1. `InvoiceHash`, `BilledAmount`, `AttemptStatus` value objects.
- 2. `Invoice` + `PaymentAttempt` with B-1…B-7; partial unique index migration.
- 3. Repository interfaces + SQLAlchemy implementations (with `UNIQUE(hash)`).
- 4. `RecordInvoice` (including duplicate detection + digest review call to Mandate).
- 5. `ProposePayment` with `ProposalRejected` for forbidden keys.
- 6. Fixture loader covering all 7 acceptance scenarios.
- 7. Event subscribers: `SettlementConfirmed` → `InvoiceSettled`; refusal → `AttemptRefused`.



## Implementation

> **Agent:** Create interface-only files. No implementation. Use Clean Architecture layers:
> 1. Read the architecture module to understand each component's role
> 2. Place domain interfaces in domain/, service interfaces in application/, DTOs in application/
> 3. Controllers/routers are CONCRETE — they do NOT get interfaces. The concrete router/handler class goes directly in interfaces/http/ without a separate contract file.
> 4. Event schemas go in domain/event/
> 5. Repository interfaces go in infrastructure/repository/
>
> The goal is a reviewed, frozen contract that implementation issues can depend on.
