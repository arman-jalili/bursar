---
guardian_issue:
  id: "ISSUE-CONTRACT-FREEZE"
  epic: "authority"
  component: "Contract Freeze"
  module: "authority"
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
    - module: ".pi/architecture/modules/authority.md"

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
    - "create: src/authority/domain/"
    - "create: src/authority/application/"
    - "create: src/authority/infrastructure/"
    - "create: src/authority/interfaces/"
---

# Contract Freeze: authority

## Intent

Define and freeze all public interfaces, contracts, and schemas for the authority
epic before any implementation begins. This prevents architecture drift — implementation
must satisfy contracts, not the other way around.

## Included Components

- Aggregate: PaymentIntent
- Aggregate: Determination
- Aggregate: CapLedger
- Entity: Reservation / Entity: Approval
- Value Objects (entity-vs-VO justification)
- Repository interfaces (owned by `domain/`)
- Ports to upstream contexts (ACL)
- Domain Services
- `PaymentIntent.issue`
- `requires_owner_signature`
- `CapLedger` cap
- `CapLedger.commit/release`
- Determination reasons
- Re-read rule
- `Approval` binding
- `Approval` single-use
- Approvals expire
- Precondition fail-closed
- Refusal has no side effect
- Ledger consistency
- No LLM
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
| 1 | `PaymentIntent.issue` | A proposal carrying its own `payee_address` cannot influence the intent: the intent uses Mandate's address and the test asserts inequality. | unit |
| 2 | `PaymentIntent.issue` | Attempt amount ≠ invoice amount → `AmountMismatch`, no intent persisted. | unit |
| 3 | `requires_owner_signature` | True for a new payee at 5 USDC and for an eligible payee at 320 USDC with threshold 25; false for eligible at 12 USDC. | unit |
| 4 | `CapLedger` cap | 6 concurrent 25 USDC attempts against a 150 USDC cap: exactly 6 reserve if headroom allows, else the excess returns `CapacityRefused` and the ledger never exceeds 150. (scenario 4) | integration (concurrency) |
| 5 | `CapLedger.commit/release` | Committing twice raises; commit then release raises; `committed + reserved` unchanged by a rejected second call. | unit |
| 6 | Determination reasons | Every `DENY` has ≥1 code from the closed set; a code outside the set fails type check. | unit |
| 7 | Re-read rule | Freeze the payee between evaluate and precondition check → precondition returns deny/`payee_frozen` and no settlement order exists. (scenario 3) | integration |
| 8 | `Approval` binding | Signature over intent A replayed for intent B (different amount) → `ApprovalRejected`, no dispatch. (scenario 5 negative) | integration |
| 9 | `Approval` single-use | Second `consume()` → raises; only one settlement event observed. | unit |
| 10 | Approvals expire | Past `expires_at` → `ApprovalExpired`, `PaymentRefused(approval_invalid)`. | unit |
| 11 | Precondition fail-closed | Mandate unreachable → `POST /v1/precondition/check` returns non-200 and Rigorix does not run the command. | integration |
| 12 | Refusal has no side effect | After any `PaymentRefused`, `reserved` and `committed` for the day are unchanged and no `settlement_orders` row exists. | integration |
| 13 | Ledger consistency | `committed` equals the sum of on-chain settled amounts for the day after a full scenario run. | integration |
| 14 | No LLM | `src/authority/` imports no model/LLM client (import-graph test). | automated |
| 15 | Layer purity | `src/authority/domain/` imports no FastAPI/SQLAlchemy/httpx. | automated |

## Full Implementation Sequence (for reference)

- 1. Shared kernel: `Money`, `AggregateRoot`, `DomainEvent`, EIP-712 spec file (`shared/eip712.py`).
- 2. `PaymentIntent` + `Determination` with A-1…A-8 (no I/O; pure tests).
- 3. `CapLedger` + `Reservation` with A-9…A-12, plus the conditional-UPDATE repository and a
- 4. `Approval` + `OwnerSignature` verification A-13…A-15, including expiry and single-use.
- 5. `MandateView` / `AttemptViewPort` adapters (read-through, no cache) + contract tests.
- 6. `EvaluateAuthority`, `ReserveCapacity` (catalog order), then `EscalateForSignature`,
- 7. `interfaces/precondition.check` fail-closed behaviour + Rigorix integration test.
- 8. Wire Settlement outcome events into `ReconcileReservation`.
- 9. Budget guard (`BUDGET_EXHAUSTED`) per ADR-006.



## Implementation

> **Agent:** Create interface-only files. No implementation. Use Clean Architecture layers:
> 1. Read the architecture module to understand each component's role
> 2. Place domain interfaces in domain/, service interfaces in application/, DTOs in application/
> 3. Controllers/routers are CONCRETE — they do NOT get interfaces. The concrete router/handler class goes directly in interfaces/http/ without a separate contract file.
> 4. Event schemas go in domain/event/
> 5. Repository interfaces go in infrastructure/repository/
>
> The goal is a reviewed, frozen contract that implementation issues can depend on.
