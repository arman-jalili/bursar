---
guardian_issue:
  id: "ISSUE-MANDATE-2"
  epic: "TBD"
  component: "Aggregate: Constitution"
  module: "mandate"
  status: planned
  priority: high
  dependencies:
    - "none"

  in_scope:
    - "Without an owner proof → `OwnerProofInvalid`, status unchanged; with proof → `ELIGIBLE` + `PayeeReapproved`."
    - "After freeze, `review_presented_digest` is a no-op and status stays `FROZEN` (P-4). (scenario 3)"
    - "All 4 statuses reachable only via the documented transitions; no other path compiles/passes."

  out_of_scope:
    - Changes to upstream components (none)
    - UI/frontend changes
    - Deployment pipeline configuration

  canonical_references:
    - module: ".pi/architecture/modules/mandate.md"
    - acceptance_criteria: ".pi/architecture/modules/mandate.md#acceptance-criteria"

  acceptance_criteria:
    - "Without an owner proof → `OwnerProofInvalid`, status unchanged; with proof → `ELIGIBLE` + `PayeeReapproved`."
    - "After freeze, `review_presented_digest` is a no-op and status stays `FROZEN` (P-4). (scenario 3)"
    - "All 4 statuses reachable only via the documented transitions; no other path compiles/passes."

  validators:
    - ci
    - tests
    - security
    - architecture
    - canonical

  implementation_notes: |
    Read .pi/architecture/modules/mandate.md BEFORE implementing.
    All Acceptance Criteria in that file must be satisfied before this issue is closed.
    Component focus: Aggregate: Constitution.
    CONCRETE IMPLEMENTATIONS MUST BE CREATED — interface stubs from the contract freeze
    are not sufficient. Each domain service/aggregate needs a concrete .impl.py file.

  file_changes:
    - "create: src/mandate/domain/"
    - "create: src/mandate/application/"
    - "create: src/mandate/infrastructure/"
    - "modify: src/mandate/interfaces/"
    -     - "update: tests/ (failing tests already generated — make them pass)"
---

# ISSUE-MANDATE-2: Implement Aggregate: Constitution — mandate

## Intent

Implement **Aggregate: Constitution** for the `mandate` module.

> ⚠️ **Read before implementing:** `.pi/architecture/modules/mandate.md`
> Every item in the **Acceptance Criteria** section of that file must be satisfied
> before this issue is closed — including adapter, mapper, and WireMock items.

## Architecture Context

- **Module:** mandate
- **Component:** Aggregate: Constitution
- **Status:** planned
- **Dependencies:** none

## In Scope (this component)

- Without an owner proof → `OwnerProofInvalid`, status unchanged; with proof → `ELIGIBLE` + `PayeeReapproved`.
- After freeze, `review_presented_digest` is a no-op and status stays `FROZEN` (P-4). (scenario 3)
- All 4 statuses reachable only via the documented transitions; no other path compiles/passes.

## Acceptance Criteria (this issue)

These acceptance criteria must be satisfied before this issue can be closed:

| # | Criterion | Verify In |
|---|-----------|-----------|
| 4 | Without an owner proof → `OwnerProofInvalid`, status unchanged; with proof → `ELIGIBLE` + `PayeeReapproved`. | unit |
| 5 | After freeze, `review_presented_digest` is a no-op and status stays `FROZEN` (P-4). (scenario 3) | unit |
| 6 | All 4 statuses reachable only via the documented transitions; no other path compiles/passes. | unit |

## Full Module Acceptance Criteria

> All items below must pass before the **epic** is closed.
> Items may be split across multiple issues — verify your component's items before creating the MR.

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

## Implementation Sequence (from module doc)

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

> **Agent instructions:**
> 1. Open `.pi/architecture/modules/mandate.md` — read the full Acceptance Criteria table
> 2. Identify which rows are your responsibility for **Aggregate: Constitution**
> 3. Create concrete implementation files (`.impl.py`) in `src/mandate/` — the interface stubs from the contract freeze are NOT enough
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
