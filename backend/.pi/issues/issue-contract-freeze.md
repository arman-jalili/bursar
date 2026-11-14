---
guardian_issue:
  id: "ISSUE-CONTRACT-FREEZE"
  epic: "console"
  component: "Contract Freeze"
  module: "console"
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
    - module: ".pi/architecture/modules/console.md"

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
    - "create: src/console/domain/"
    - "create: src/console/application/"
    - "create: src/console/infrastructure/"
    - "create: src/console/interfaces/"
---

# Contract Freeze: console

## Intent

Define and freeze all public interfaces, contracts, and schemas for the console
epic before any implementation begins. This prevents architecture drift — implementation
must satisfy contracts, not the other way around.

## Included Components

- Application services (catalog)
- Anti-corruption layer — field whitelists
- Ports (upstream clients)
- Whitelist
- Exact fields
- Passthrough
- Read-only
- Payer copy
- Simulated payout
- Refusal reason
- Verify toggle
- No domain layer
- Mobile

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
| 1 | Whitelist | An upstream payload with an extra field (`internal_note`) does not appear in any console response. | unit |
| 2 | Exact fields | The inbox renders `payee_address` and `bank_digest` byte-identically to Authority's intent (no truncation, no re-checksumming). | integration |
| 3 | Passthrough | `POST /signature` forwards the signature unmodified; a recorded request body equals the received one. | integration |
| 4 | Read-only | No console endpoint can create an intent, attempt or settlement order; a scope test proves the owner token cannot reach those. | integration (auth matrix) |
| 5 | Payer copy | Payer endpoints contain none of: USDC, gas, chain, wallet, nullifier, determination (grep on fixtures). | automated |
| 6 | Simulated payout | Every payer bill with a settlement carries `payout_simulated: true` and the demo label. | integration |
| 7 | Refusal reason | A refused payment appears for the owner with a human-readable reason derived from the reason codes. (scenarios 2/3/4) | integration |
| 8 | Verify toggle | Evidence view shows `verified` for an untouched envelope and `tampered` after one byte is flipped. (scenario 7) | integration |
| 9 | No domain layer | `src/console/domain/` does not exist; its appearance fails the adapter-purity check. | automated |
| 10 | Mobile | Both surfaces usable at 390×844 with no horizontal scroll; owner approval takes ≤3 taps from the notification. (NFR-011) | manual |

## Full Implementation Sequence (for reference)

- 1. OpenAPI schema for the eight console endpoints (hour 6, unblocks the React team).
- 2. ACL whitelists + plain-language mapping table with unit tests.
- 3. `ProjectPayerBills` (read-only, no dependencies on signing) — the safest first surface.
- 4. `ProjectApprovalInbox` with exact intent fields and `typed_data_hash`.
- 5. Signature passthrough endpoint (no transformation) + rejection copy.
- 6. `ProjectEvidence` + verification proxy with the verified/tampered toggle.
- 7. Empty/loading/error states; mobile viewport pass.



## Implementation

> **Agent:** Create interface-only files. No implementation. Use Clean Architecture layers:
> 1. Read the architecture module to understand each component's role
> 2. Place domain interfaces in domain/, service interfaces in application/, DTOs in application/
> 3. Controllers/routers are CONCRETE — they do NOT get interfaces. The concrete router/handler class goes directly in interfaces/http/ without a separate contract file.
> 4. Event schemas go in domain/event/
> 5. Repository interfaces go in infrastructure/repository/
>
> The goal is a reviewed, frozen contract that implementation issues can depend on.
