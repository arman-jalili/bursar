---
guardian_issue:
  id: "ISSUE-CONSOLE-8"
  epic: "TBD"
  component: "Payer copy"
  module: "console"
  status: planned
  priority: high
  dependencies:
    - "none"

  in_scope:
    - "Payer endpoints contain none of: USDC, gas, chain, wallet, nullifier, determination (grep on fixtures)."

  out_of_scope:
    - Changes to upstream components (none)
    - UI/frontend changes
    - Deployment pipeline configuration

  canonical_references:
    - module: ".pi/architecture/modules/console.md"
    - acceptance_criteria: ".pi/architecture/modules/console.md#acceptance-criteria"

  acceptance_criteria:
    - "Payer endpoints contain none of: USDC, gas, chain, wallet, nullifier, determination (grep on fixtures)."

  validators:
    - ci
    - tests
    - security
    - architecture
    - canonical

  implementation_notes: |
    Read .pi/architecture/modules/console.md BEFORE implementing.
    All Acceptance Criteria in that file must be satisfied before this issue is closed.
    Component focus: Payer copy.
    CONCRETE IMPLEMENTATIONS MUST BE CREATED — interface stubs from the contract freeze
    are not sufficient. Each domain service/aggregate needs a concrete .impl.py file.

  file_changes:
    - "create: src/console/domain/"
    - "create: src/console/application/"
    - "create: src/console/infrastructure/"
    - "modify: src/console/interfaces/"
    -     - "create: tests/"
---

# ISSUE-CONSOLE-8: Implement Payer copy — console

## Intent

Implement **Payer copy** for the `console` module.

> ⚠️ **Read before implementing:** `.pi/architecture/modules/console.md`
> Every item in the **Acceptance Criteria** section of that file must be satisfied
> before this issue is closed — including adapter, mapper, and WireMock items.

## Architecture Context

- **Module:** console
- **Component:** Payer copy
- **Status:** planned
- **Dependencies:** none

## In Scope (this component)

- Payer endpoints contain none of: USDC, gas, chain, wallet, nullifier, determination (grep on fixtures).

## Acceptance Criteria (this issue)

These acceptance criteria must be satisfied before this issue can be closed:

| # | Criterion | Verify In |
|---|-----------|-----------|
| 5 | Payer endpoints contain none of: USDC, gas, chain, wallet, nullifier, determination (grep on fixtures). | automated |

## Full Module Acceptance Criteria

> All items below must pass before the **epic** is closed.
> Items may be split across multiple issues — verify your component's items before creating the MR.

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

## Implementation Sequence (from module doc)

- 1. OpenAPI schema for the eight console endpoints (hour 6, unblocks the React team).
- 2. ACL whitelists + plain-language mapping table with unit tests.
- 3. `ProjectPayerBills` (read-only, no dependencies on signing) — the safest first surface.
- 4. `ProjectApprovalInbox` with exact intent fields and `typed_data_hash`.
- 5. Signature passthrough endpoint (no transformation) + rejection copy.
- 6. `ProjectEvidence` + verification proxy with the verified/tampered toggle.
- 7. Empty/loading/error states; mobile viewport pass.

## Implementation

> **Agent instructions:**
> 1. Open `.pi/architecture/modules/console.md` — read the full Acceptance Criteria table
> 2. Identify which rows are your responsibility for **Payer copy**
> 3. Create concrete implementation files (`.impl.py`) in `src/console/` — the interface stubs from the contract freeze are NOT enough
> 4. Each domain aggregate/service must have a working implementation with business logic
> 5. Verify each AC row is satisfied in `src/` before marking done
> 6. Run validators and create MR

### Steps

1. Read canonical architecture references
2. Create domain entities and interfaces
3. Implement application service/handler
4. Add infrastructure connections
5. Write unit tests (≥ 90% coverage)
6. Write integration tests
7. Run all validators
8. Create MR
