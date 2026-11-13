---
guardian_issue:
  id: "ISSUE-AUTHORITY-6"
  epic: "TBD"
  component: "Repository interfaces (owned by `domain/`)"
  module: "authority"
  status: planned
  priority: high
  dependencies:
    - "none"

  in_scope:
    - "A proposal carrying its own `payee_address` cannot influence the intent: the intent uses Mandate's address and the test asserts inequality."
    - "Attempt amount ≠ invoice amount → `AmountMismatch`, no intent persisted."
    - "True for a new payee at 5 USDC and for an eligible payee at 320 USDC with threshold 25; false for eligible at 12 USDC."
    - "6 concurrent 25 USDC attempts against a 150 USDC cap: exactly 6 reserve if headroom allows, else the excess returns `CapacityRefused` and the ledger never exceeds 150. (scenario 4)"

  out_of_scope:
    - Changes to upstream components (none)
    - UI/frontend changes
    - Deployment pipeline configuration

  canonical_references:
    - module: ".pi/architecture/modules/authority.md"
    - acceptance_criteria: ".pi/architecture/modules/authority.md#acceptance-criteria"

  acceptance_criteria:
    - "A proposal carrying its own `payee_address` cannot influence the intent: the intent uses Mandate's address and the test asserts inequality."
    - "Attempt amount ≠ invoice amount → `AmountMismatch`, no intent persisted."
    - "True for a new payee at 5 USDC and for an eligible payee at 320 USDC with threshold 25; false for eligible at 12 USDC."
    - "6 concurrent 25 USDC attempts against a 150 USDC cap: exactly 6 reserve if headroom allows, else the excess returns `CapacityRefused` and the ledger never exceeds 150. (scenario 4)"

  validators:
    - ci
    - tests
    - security
    - architecture
    - canonical

  implementation_notes: |
    Read .pi/architecture/modules/authority.md BEFORE implementing.
    All Acceptance Criteria in that file must be satisfied before this issue is closed.
    Component focus: Repository interfaces (owned by `domain/`).
    CONCRETE IMPLEMENTATIONS MUST BE CREATED — interface stubs from the contract freeze
    are not sufficient. Each domain service/aggregate needs a concrete .impl.py file.

  file_changes:
    - "create: src/authority/domain/"
    - "create: src/authority/application/"
    - "create: src/authority/infrastructure/"
    - "modify: src/authority/interfaces/"
    -     - "update: tests/ (failing tests already generated — make them pass)"
---

# ISSUE-AUTHORITY-6: Implement Repository interfaces (owned by `domain/`) — authority

## Intent

Implement **Repository interfaces (owned by `domain/`)** for the `authority` module.

> ⚠️ **Read before implementing:** `.pi/architecture/modules/authority.md`
> Every item in the **Acceptance Criteria** section of that file must be satisfied
> before this issue is closed — including adapter, mapper, and WireMock items.

## Architecture Context

- **Module:** authority
- **Component:** Repository interfaces (owned by `domain/`)
- **Status:** planned
- **Dependencies:** none

## In Scope (this component)

- A proposal carrying its own `payee_address` cannot influence the intent: the intent uses Mandate's address and the test asserts inequality.
- Attempt amount ≠ invoice amount → `AmountMismatch`, no intent persisted.
- True for a new payee at 5 USDC and for an eligible payee at 320 USDC with threshold 25; false for eligible at 12 USDC.
- 6 concurrent 25 USDC attempts against a 150 USDC cap: exactly 6 reserve if headroom allows, else the excess returns `CapacityRefused` and the ledger never exceeds 150. (scenario 4)

## Acceptance Criteria (this issue)

These acceptance criteria must be satisfied before this issue can be closed:

| # | Criterion | Verify In |
|---|-----------|-----------|
| 1 | A proposal carrying its own `payee_address` cannot influence the intent: the intent uses Mandate's address and the test asserts inequality. | unit |
| 2 | Attempt amount ≠ invoice amount → `AmountMismatch`, no intent persisted. | unit |
| 3 | True for a new payee at 5 USDC and for an eligible payee at 320 USDC with threshold 25; false for eligible at 12 USDC. | unit |
| 4 | 6 concurrent 25 USDC attempts against a 150 USDC cap: exactly 6 reserve if headroom allows, else the excess returns `CapacityRefused` and the ledger never exceeds 150. (scenario 4) | integration (concurrency) |

## Full Module Acceptance Criteria

> All items below must pass before the **epic** is closed.
> Items may be split across multiple issues — verify your component's items before creating the MR.

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

## Implementation Sequence (from module doc)

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

> **Agent instructions:**
> 1. Open `.pi/architecture/modules/authority.md` — read the full Acceptance Criteria table
> 2. Identify which rows are your responsibility for **Repository interfaces (owned by `domain/`)**
> 3. Create concrete implementation files (`.impl.py`) in `src/authority/` — the interface stubs from the contract freeze are NOT enough
> 4. Each domain aggregate/service must have a working implementation with business logic
> 5. Verify each AC row is satisfied in `src/` before marking done
> 6. Run validators and create MR

### Steps

1. Read canonical architecture references
2. Run the pre-generated failing tests: `cd tests && pytest`
3. Verify tests FAIL (Red phase)
4. Implement domain entities and interfaces
5. Implement application service/handler
6. Add infrastructure connections
7. Run tests again — they should PASS (Green phase)
8. Refactor if needed (Refactor phase)
9. Write integration tests
10. Run all validators
11. Create MR
