---
guardian_issue:
  id: "ISSUE-CONTRACT-FREEZE"
  epic: "mandate"
  component: "Contract Freeze"
  module: "mandate"
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
    - module: ".pi/architecture/modules/mandate.md"

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
    - "create: src/mandate/domain/"
    - "create: src/mandate/application/"
    - "create: src/mandate/infrastructure/"
    - "create: src/mandate/interfaces/"
---

# Contract Freeze: mandate

## Intent

Define and freeze all public interfaces, contracts, and schemas for the mandate
epic before any implementation begins. This prevents architecture drift — implementation
must satisfy contracts, not the other way around.

## Included Components

- Aggregate: Household
- Aggregate: Constitution
- Value Objects (with entity-vs-VO justification)
- Repository interfaces (owned by `domain/`)
- Domain Services
- `BankDigest`
- `Cap` / `Threshold`
- `Payee.review_presented_digest`
- `Payee.reapprove`

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
| 1 | `BankDigest` | Two digests from identical routing details are equal; a one-character change alters the hash. | unit |
| 2 | `Cap` / `Threshold` | `Cap(0)` and `Cap(-1)` raise; `Threshold > Cap` raises at constitution append. | unit |
| 3 | `Payee.review_presented_digest` | Mismatch sets `QUARANTINED`, emits `PayeeDigestChanged` + `PayeeQuarantined`, and leaves `address` **byte-identical**. (scenario 2) | unit |
| 4 | `Payee.reapprove` | Without an owner proof → `OwnerProofInvalid`, status unchanged; with proof → `ELIGIBLE` + `PayeeReapproved`. | unit |
| 5 | `Payee.freeze` | After freeze, `review_presented_digest` is a no-op and status stays `FROZEN` (P-4). (scenario 3) | unit |
| 6 | `Payee` state machine | All 4 statuses reachable only via the documented transitions; no other path compiles/passes. | unit |
| 7 | `Constitution.append` | Requires owner proof; supersedes exactly one version; old version still readable by number. | unit |
| 8 | `Constitution` in force | `in_force` raises `ConstitutionCorrupted` when 0 or 2 versions are live. | unit |
| 9 | Agent actor | Any agent-role `PartyRef` on `register_payee`/`freeze`/`append` → `OwnerActionRequired` + HTTP 403. | integration |
| 10 | Digest endpoint | `POST /v1/payees/{id}/presented-digest` returns 200 and no other state change. | integration |
| 11 | Eligibility read-through | Two consecutive `GET /v1/payees/{id}/eligibility` calls with a freeze in between return `allow` then `deny` (no caching). | integration |
| 12 | Events | Each command publishes exactly its documented events to `mandate_outbox` in the same transaction. | integration |
| 13 | Layer purity | `src/mandate/domain/` imports no FastAPI/SQLAlchemy/httpx (dip-domain gate). | automated |

## Full Implementation Sequence (for reference)

- 1. Shared kernel: `AggregateRoot`, `ValueObject`, `DomainEvent`, `OwnerSignatureProof`, errors.
- 2. `BankDigest` + `Cap` + `Threshold` + `PayeeStatus` + validation tests (no I/O, fast).
- 3. `Payee` aggregate with all six invariants P-1…P-6 and its state machine tests.
- 4. `Constitution` + `ConstitutionVersion` with H-4…H-8.
- 5. `Household` + `Owner`/`Payer`/`Agent` with H-1…H-3.
- 6. Repository interfaces in `domain/`, SQLAlchemy implementations + migrations `001_mandate`.
- 7. Application services (catalog order) each with one transaction.
- 8. Interfaces/HTTP + scopes from ADR-005; authorization matrix test.
- 9. Wire `PayeeQuarantined`/`PayeeFrozen` into Authority's dispatch-time read (scenarios 2, 3).



## Implementation

> **Agent:** Create interface-only files. No implementation. Use Clean Architecture layers:
> 1. Read the architecture module to understand each component's role
> 2. Place domain interfaces in domain/, service interfaces in application/, DTOs in application/
> 3. Controllers/routers are CONCRETE — they do NOT get interfaces. The concrete router/handler class goes directly in interfaces/http/ without a separate contract file.
> 4. Event schemas go in domain/event/
> 5. Repository **interfaces/ABCs** go in `domain/`; their implementations go in `infrastructure/repository/`
>    (ADR-002: the domain declares the port, the adapter fulfils it)
>
> The goal is a reviewed, frozen contract that implementation issues can depend on.
