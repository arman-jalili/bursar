---
guardian_issue:
  id: "ISSUE-BILLING-6"
  epic: "TBD"
  component: "Forbidden fields"
  module: "billing"
  status: planned
  priority: high
  dependencies:
    - "none"

  in_scope:
    - "Proposal with `payee_address`, `command`, `cap` or `threshold` → 422 `PROPOSAL_REJECTED`, zero attempts persisted."

  out_of_scope:
    - Changes to upstream components (none)
    - UI/frontend changes
    - Deployment pipeline configuration

  canonical_references:
    - module: ".pi/architecture/modules/billing.md"
    - acceptance_criteria: ".pi/architecture/modules/billing.md#acceptance-criteria"

  acceptance_criteria:
    - "Proposal with `payee_address`, `command`, `cap` or `threshold` → 422 `PROPOSAL_REJECTED`, zero attempts persisted."

  validators:
    - ci
    - tests
    - security
    - architecture
    - canonical

  implementation_notes: |
    Read .pi/architecture/modules/billing.md BEFORE implementing.
    All Acceptance Criteria in that file must be satisfied before this issue is closed.
    Component focus: Forbidden fields.
    CONCRETE IMPLEMENTATIONS MUST BE CREATED — interface stubs from the contract freeze
    are not sufficient. Each domain service/aggregate needs a concrete .impl.py file.

  file_changes:
    - "create: src/billing/domain/"
    - "create: src/billing/application/"
    - "create: src/billing/infrastructure/"
    - "modify: src/billing/interfaces/"
    -     - "create: tests/"
---

# ISSUE-BILLING-6: Implement Forbidden fields — billing

## Intent

Implement **Forbidden fields** for the `billing` module.

> ⚠️ **Read before implementing:** `.pi/architecture/modules/billing.md`
> Every item in the **Acceptance Criteria** section of that file must be satisfied
> before this issue is closed — including adapter, mapper, and WireMock items.

## Architecture Context

- **Module:** billing
- **Component:** Forbidden fields
- **Status:** planned
- **Dependencies:** none

## In Scope (this component)

- Proposal with `payee_address`, `command`, `cap` or `threshold` → 422 `PROPOSAL_REJECTED`, zero attempts persisted.

## Acceptance Criteria (this issue)

These acceptance criteria must be satisfied before this issue can be closed:

| # | Criterion | Verify In |
|---|-----------|-----------|
| 4 | Proposal with `payee_address`, `command`, `cap` or `threshold` → 422 `PROPOSAL_REJECTED`, zero attempts persisted. | integration |

## Full Module Acceptance Criteria

> All items below must pass before the **epic** is closed.
> Items may be split across multiple issues — verify your component's items before creating the MR.

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

## Implementation Sequence (from module doc)

- 1. `InvoiceHash`, `BilledAmount`, `AttemptStatus` value objects.
- 2. `Invoice` + `PaymentAttempt` with B-1…B-7; partial unique index migration.
- 3. Repository interfaces + SQLAlchemy implementations (with `UNIQUE(hash)`).
- 4. `RecordInvoice` (including duplicate detection + digest review call to Mandate).
- 5. `ProposePayment` with `ProposalRejected` for forbidden keys.
- 6. Fixture loader covering all 7 acceptance scenarios.
- 7. Event subscribers: `SettlementConfirmed` → `InvoiceSettled`; refusal → `AttemptRefused`.

## Implementation

> **Agent instructions:**
> 1. Open `.pi/architecture/modules/billing.md` — read the full Acceptance Criteria table
> 2. Identify which rows are your responsibility for **Forbidden fields**
> 3. Create concrete implementation files (`.impl.py`) in `src/billing/` — the interface stubs from the contract freeze are NOT enough
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
