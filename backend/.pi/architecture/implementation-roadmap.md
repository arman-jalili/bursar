# Implementation Roadmap

<!--
@canonical .pi/architecture/implementation-roadmap.md
Status: Accepted
Date: 2026-11-13
Session: 432050ea-0419-44ba-8ac4-b239242634b4
-->

> **24-hour implementation override (analyst, 2026-11-13).** The architecture is not wrong; the
> risk is optional surface crowding out the three must scenes. The authoritative scope is
> `docs/BURSAR-ARCH-REVIEW.md` and `docs/BURSAR-BUILD-CONTRACT.md`. Must-fix: one public
> **11-endpoint `/api` contract** (the 42 module endpoints are internal only); **Evidence must
> verify Rigorix envelopes** (a separate app receipt log is optional, not a replacement); the
> command is `/opt/bursar/bin/payctl --intent <id>`; and claims must distinguish a Rigorix
> envelope from an app record (plan-time denials have no engine envelope).
> Optional richness — outbox, API scopes, payer view, Alembic, cost extras — may ship if it is
> generated and tested without delaying G2. When the clock is short, use the must/should/stretch
> table in the review as a fallback order, not a prohibition.

## Overview

This roadmap orders the six bounded contexts by dependency chain for the Proximata Hackathon
'26 timebox: **24 hours, 2–4 people, code freeze Saturday 14 November 2026 15:00, demos 16:00**.

Phases are therefore measured in **hours, not days**. The `## Phase N` structure, module tables,
migrations and acceptance criteria are unchanged — only the unit of time is honest.

**Format conventions:**
- `## Phase 0: Project Bootstrap` is MINIMUM project setup — not a bounded context. No
  `### Modules` rows, no context folders.
- Each `## Phase N` (N≥1) contains exactly one bounded context's build phase.
- **Invariant:** each bounded context appears in exactly ONE `### Modules` table. Six modules,
  six rows, across Phases 1–6.
- Modules a phase merely *uses* appear under `### Dependencies`, never as Modules rows.
- Hardening and rehearsal are **milestones and acceptance criteria inside phases**, not a phase
  of their own (a phase that only re-touches built modules is not a phase).

**Dependency order derived from the context map:**

```
Mandate (pure upstream)
   ├── Billing          (conformist)
   └── Authority        (conformist) ── needs Billing (ACL) ──┐
                                        Settlement (partnership) ── Evidence (partnership)
                                                                     └── Console (all read-only)
```

---

## Phase 0: Project Bootstrap (Hours 0–1)

**Goal:** A booting, lint-clean, validator-clean skeleton with the shared kernel and migration
tooling — created via `/project create`. No bounded context folders.

### Modules

Bootstrap only — no bounded contexts.

### Dependencies

- None

### Database Migrations

- `000_bootstrap`: migration tooling installed (Alembic); creates **no** module tables.

### Deliverables

| Area | Deliverable |
|---|---|
| Toolchain | `pyproject.toml` (Python 3.12), `uv`/poetry lock, `ruff`, `mypy`, `pytest`, `pytest-asyncio` |
| Layout | `src/shared/` (shared kernel), `src/<context>/` folders created **later, per phase** |
| Shared kernel | `AggregateRoot`, `ValueObject`, `DomainEvent`, `Repository`, `Money`, `Clock`, error envelope base |
| Config | `pydantic-settings` + `.env.example` (`HMAC_KEY`, `OWNER_ADDRESS`, `SETTLEMENT_PRIVATE_KEY`, `RPC_URL`, `CHAIN=anvil\|sepolia`, `BUDGET_USDC`) |
| Error envelope | `{error: {code, message, retryable, correlation_id}}` + handlers |
| Logging | structured JSON logs, correlation id middleware, no-secret filter |
| DB | SQLite + WAL + `busy_timeout`; Alembic wired, no tables |
| CI | ruff, mypy, pytest, `.pi/scripts` architecture validators |
| Entrypoints | `authority-service` (`:8001`) and `console-api` (`:8000`) with `/healthz`, `/readyz` |
| Foundry | `foundry.toml`, empty `contracts/` scaffold, Anvil make target |

### Acceptance Criteria

- [ ] `make install && make test` passes on an empty suite.
- [ ] Both services boot and answer `/healthz` and `/readyz`.
- [ ] `ruff`, `mypy`, `pytest`, and the architecture validators are green.
- [ ] Alembic upgrades and downgrades a clean database.
- [ ] `.env.example` documents every variable; no secret is committed.
- [ ] `src/` contains no `<context>/` package yet (bootstrap purity).

---

## Phase 1: Mandate (Hours 1–4)

**Goal:** The constitution and payee registry exist, are owner-governed, and can quarantine a
payee whose bank digest changed.

### Modules

| Module | Deliverables | Architecture Doc |
|--------|-------------|------------------|
| **Mandate** | `Household`, `Constitution`+`ConstitutionVersion`, `Payee`, `BankDigest`/`Cap`/`Threshold`/`PayeeStatus`/`PartyRef`, 3 repository interfaces + SQLAlchemy impls, 6 catalog application services, 11 REST endpoints, 12 events → outbox | `.pi/architecture/modules/mandate.md` |

### Dependencies

- Phase 0 (shared kernel: `AggregateRoot`, `Money`, `DomainEvent`, error envelope, Alembic)

### Database Migrations

- `001_mandate`: `mandate_households`, `mandate_constitutions`, `mandate_constitution_versions`
  (`UNIQUE(household_id, version)`, partial unique index on `status='in_force'`),
  `mandate_payees` (`UNIQUE(household_id, name)`), `mandate_outbox`

### Acceptance Criteria

- [ ] Payee invariant tests P-1…P-6 pass, including "mismatch quarantines and leaves the address
      byte-identical" (scenario 2, unit level).
- [ ] Constitution H-4…H-8 pass: exactly one in-force, threshold ≤ cap, immutable versions.
- [ ] Agent-scoped credentials receive 403 on every mandate write endpoint.
- [ ] `GET /v1/payees/{id}/eligibility` reflects a freeze between two consecutive calls (no cache).
- [ ] Every command writes exactly its documented events to `mandate_outbox` in one transaction.

---

## Phase 2: Billing (Hours 4–6)

**Goal:** Invoices and payment attempts exist, and a proposal carrying forbidden fields is
rejected outright.

### Modules

| Module | Deliverables | Architecture Doc |
|--------|-------------|------------------|
| **Billing** | `Invoice`, `PaymentAttempt`, `InvoiceHash`/`BilledAmount`/`AttemptStatus`, 2 repository interfaces + impls, `RecordInvoice`, `ProposePayment`, 5 REST endpoints, 7 events → outbox, fixture loader for 7 scenarios | `.pi/architecture/modules/billing.md` |

### Dependencies

- Phase 0 (shared kernel)
- **Mandate** — provides payee id, verified digest baseline, and the presented-digest endpoint
  that triggers quarantine (conformist)

### Database Migrations

- `002_billing`: `billing_invoices` (`UNIQUE(hash)`), `billing_attempts` (partial unique index
  on `invoice_id` where status is non-terminal), `billing_outbox`

### Acceptance Criteria

- [ ] Duplicate invoice hash → original invoice + `DuplicateInvoiceDetected`, no second row.
- [ ] Two concurrent proposals for one invoice → exactly one attempt.
- [ ] Proposal containing `payee_address`, `command`, `cap` or `threshold` → 422
      `PROPOSAL_REJECTED` with the offending field names, nothing persisted (scenario 2 input).
- [ ] Presented digest ≠ Mandate's verified digest → Mandate quarantines the payee.
- [ ] Fixtures cover all 7 acceptance scenarios with stable invoice hashes.

---

## Phase 3: Authority (Hours 6–10)

**Goal:** The decision engine exists and is fail-closed: it allows, denies or escalates with
reason codes, and its cap ledger cannot be over-booked under concurrency.

### Modules

| Module | Deliverables | Architecture Doc |
|--------|-------------|------------------|
| **Authority** | `PaymentIntent`, `Determination`, `CapLedger`+`Reservation`, `Approval`+`OwnerSignature`, `Money`/`DeterminationVerdict`, 5 catalog application services, `POST /v1/precondition/check`, 8 REST endpoints, 12 events → outbox, EIP-712 spec shared with Solidity | `.pi/architecture/modules/authority.md` |

### Dependencies

- Phase 0 (shared kernel, EIP-712 spec stub)
- **Mandate** — in-force constitution + payee eligibility, read-through with no cache
- **Billing** — attempt + invoice amount behind an ACL that exposes no routing fields
- **Phase 0 Anvil** — for the signature round-trip test only (not for logic)

### Database Migrations

- `003_authority`: `authority_intents`, `authority_determinations`,
  `authority_cap_ledger` (`UNIQUE(day)`), `authority_reservations`, `authority_approvals`,
  `authority_outbox`

### Acceptance Criteria

- [ ] Cap A-9 passes a 6-way concurrency test: 6 × 25 USDC against a 150 USDC cap, ledger never
      exceeds the cap, excess refused with `capacity_exceeded` (scenario 4).
- [ ] Reservation A-10: commit-twice and commit-then-release both raise.
- [ ] Freeze between evaluate and precondition-check → deny `payee_frozen`, zero settlement
      orders (scenario 3).
- [ ] Signature bound to intent A replayed for intent B → `ApprovalRejected`, no dispatch
      (scenario 5, negative case).
- [ ] Approval is single-use and expires.
- [ ] Mandate unreachable → precondition check returns non-200 (fail closed).
- [ ] Every `DENY` carries ≥1 reason code from the closed set.
- [ ] `src/authority/` imports no LLM client (import-graph test).
- [ ] A refused payment leaves `committed`/`reserved` unchanged and creates no settlement order.

---

## Phase 4: Settlement (Hours 10–14)

**Goal:** USDC actually moves once — and only once — through Rigorix `run_command` and
`PaymentRouter`, with a receipt that reconciles the ledger.

### Modules

| Module | Deliverables | Architecture Doc |
|--------|-------------|------------------|
| **Settlement** | `SettlementOrder`, `ChainReceipt`, `Nullifier`/`PayeeAddress`/`ChainNetwork`/`SettlementStatus`, `NullifierPolicy`/`FinalityPolicy`, `DispatchPayment`, `SettleOnce`, 6 REST endpoints, 7 events → outbox, `PaymentRouter.sol` + Foundry deploy scripts, Rigorix `run_command` adapter, web3 receipt poller | `.pi/architecture/modules/settlement.md` |

### Dependencies

- Phase 0 (Foundry/Anvil, config)
- **Authority** — `PaymentAllowed` / `ApprovalGranted` as the dispatch gate, and the `intent_id`
  contract (partnership)
- **Mandate** — payee address as frozen on the intent (conformist)
- **Rigorix** — `.rigorix/preconditions.toml`, `sequence-policy.toml`, `capacity.toml`

### Database Migrations

- `004_settlement`: `settlement_orders` (`UNIQUE(intent_id)`, `tx_hash` unique when set),
  `settlement_nullifiers` (`UNIQUE(nullifier)` — the local double-pay lock),
  `settlement_receipts`, `settlement_outbox`

### Acceptance Criteria

- [ ] Scenario 1 end-to-end on Anvil: allow → dispatch → `SettlementConfirmed` → cap committed
      → invoice settled → receipt verifies.
- [ ] Write-ahead hash: kill the process after `mark_submitted`, restart → same tx re-polled, no
      second transaction.
- [ ] Scenario 6, app path: replay of a settled invoice → `DuplicateSettlementBlocked`, zero
      transactions.
- [ ] Scenario 6, bypass path: direct contract call with a spent nullifier reverts; app records
      `SettlementReverted` (a refusal, never a retry).
- [ ] `run_command` uses the fixed `payments.dispatch` path; no API field can supply a command.
- [ ] Revert produces exactly one `SettlementReverted` and releases the reservation.
- [ ] Sepolia deployment documented with chain id / router / USDC in `ChainNetwork`.

---

## Phase 5: Evidence (Hours 14–16)

**Goal:** Every attempt — including every refusal — leaves a signed envelope whose hash is
anchored on-chain, and one flipped byte fails verification.

### Modules

| Module | Deliverables | Architecture Doc |
|--------|-------------|------------------|
| **Evidence** | `EvidenceEnvelope`, `Anchor`, `EnvelopeHash`/`VerificationResult`, canonical encoder, HMAC signer, append-only store, `AnchorPolicy`, `SealEvidence`, `VerifyEvidence`, 4 REST endpoints, 3 events | `.pi/architecture/modules/evidence.md` |

### Dependencies

- Phase 0 (config: `HMAC_KEY` from operator env)
- **Authority** — all determinations and refusals (open-host publisher)
- **Settlement** — receipts/reverts + `POST /v1/anchors` (partnership)
- **Billing**, **Mandate** — invoice/proposal and payee-status events

### Database Migrations

- `005_evidence`: `evidence_envelopes` (append-only, `previous_hash` chain),
  `evidence_anchors` (`UNIQUE(envelope_hash)`), `evidence_processed_events`
  (`UNIQUE(event_id, handler)`), `evidence_outbox`

### Acceptance Criteria

- [ ] Canonical encoding is byte-deterministic across runs and key orderings.
- [ ] Every event in ADR-003's delivery table produces exactly one envelope with a valid HMAC.
- [ ] A denied payment produces a `PaymentRefused` envelope carrying the reason codes
      (scenario 2/3/4 all yield verifiable refusals).
- [ ] Same `event_id` delivered 3× → 1 envelope.
- [ ] Scenario 7: untouched envelope verifies with its anchor tx; one altered byte yields
      `HMAC_MISMATCH` naming the field; a wrong anchor yields `ANCHOR_MISMATCH`.
- [ ] The HMAC key appears in no payload, log line or DB column (grep test).
- [ ] Stopping Evidence does not block dispatch (witness, not guard).

---

## Phase 6: Console (Hours 16–20)

**Goal:** A non-technical viewer understands a blocked payment without explanation, and the
owner signs the exact intent in ≤3 taps.

### Modules

| Module | Deliverables | Architecture Doc |
|--------|-------------|------------------|
| **Console** | ACL whitelist projections, `ProjectApprovalInbox`, `ProjectPayerBills`, `ProjectEvidence`, 8 REST endpoints, plain-language status table, OpenAPI-driven React/TS/Vite app (owner inbox, payer bills, evidence viewer) | `.pi/architecture/modules/console.md` |

### Dependencies

- Phase 0 (OpenAPI tooling, console-api entrypoint)
- **Authority** — approval inbox, determinations, signature passthrough (anticorruption-layer)
- **Evidence** — envelope list + verification (open-host)
- **Mandate** — constitution version, payee status (open-host, display only)
- **Billing** — invoice list and status
- **Settlement** — receipt (tx hash, settled time)

### Database Migrations

- `006_console`: `console_read_models` (optional projection cache; may be omitted if events feed
  in-memory read models — record the choice here before coding).

### Acceptance Criteria

- [ ] OpenAPI schema was published by hour 6 and the React app ran against mocks before this
      phase started (NFR-006).
- [ ] Upstream payload with an extra field never appears in a console response (whitelist).
- [ ] The inbox renders `payee_address` and `bank_digest` byte-identically to the intent.
- [ ] `POST /v1/console/approvals/{id}/signature` forwards the signature unmodified.
- [ ] No console endpoint can create an intent, attempt or settlement order (auth matrix).
- [ ] Payer screens contain none of: USDC, gas, chain, wallet, nullifier, determination.
- [ ] Every settled payer bill carries `payout_simulated: true` with the demo label.
- [ ] Scenario 7's verified/tampered toggle works from the UI.
- [ ] Owner approval completes in ≤3 taps at 390×844 (NFR-011).
- [ ] `src/console/domain/` does not exist.

---

## Dependency Graph

```
Phase 0  Bootstrap (shared kernel, Alembic, entrypoints, Anvil)
    │
    ▼
Phase 1  Mandate ─────────────────────────────────┐   (pure upstream)
    │                                             │
    ▼                                             │
Phase 2  Billing ────────────────┐                │
    │                            │                │
    ▼                            ▼                ▼
Phase 3  Authority ◀─────────────┘  (Mandate reads, Billing ACL)
    │
    ▼
Phase 4  Settlement ◀── Rigorix config + PaymentRouter.sol
    │
    ▼
Phase 5  Evidence ◀── consumes Authority + Settlement (+ Billing, Mandate events)
    │
    ▼
Phase 6  Console ◀── reads Authority, Evidence, Mandate, Billing, Settlement
```

**Cross-phase references (uses, not builds):**

| Phase | Uses | Provides to |
|---|---|---|
| 2 Billing | Mandate (payee id, digest baseline, presented-digest endpoint) | Authority: attempt + invoice amount behind ACL |
| 3 Authority | Mandate (constitution/eligibility, re-read), Billing (attempt) | Settlement: allow gate + `intent_id`; Evidence: determinations/refusals |
| 4 Settlement | Authority (gate), Mandate (payee address via intent), Rigorix | Evidence: receipts/reverts + anchor write; Authority: commit/release |
| 5 Evidence | Authority, Settlement, Billing, Mandate events | Console: verification + envelopes |
| 6 Console | Authority, Evidence, Mandate, Billing, Settlement (read-only) | — (edge) |

## Effort Estimates

| Phase | Modules | Estimated Hours | Risk | Dependencies | Notes |
|---|---|---|---|---|---|
| P0 Bootstrap | 0 | 1 | Low | None | `/project create`; keeps context folders out |
| P1 Mandate | 1 | 3 | Medium | P0 | Most invariants; entirely unit-testable |
| P2 Billing | 1 | 2 | Low | P0, P1 | Straightforward; fixture quality matters |
| P3 Authority | 1 | 4 | **High** | P0, P1, P2 | Cap concurrency + EIP-712 binding are the two hardest items |
| P4 Settlement | 1 | 4 | **High** | P0, P3, Rigorix | Rigorix integration and nonce/nullifier handling |
| P5 Evidence | 1 | 2 | Medium | P0, P3, P4 | Deterministic encoding; anchoring policy |
| P6 Console | 1 | 4 | Medium | P0–P5 | Frontend runs in parallel from hour 6 |
| **Total** | **6** | **20** | — | — | Leaves ~4h for hardening + rehearsal |

Effort is **serial**; with 2–4 people, P6 (frontend) runs in parallel from hour 6 and P1/P2 can
be split. The four-hour reserve is not optional — it is the difference between "demo works" and
"demo worked once".

## Key Milestones

| Milestone | Target | What's True |
|---|---|---|
| **M0: Skeleton boots** | Hour 1 | Both services answer `/healthz`; validators green; no context folders. |
| **M1: API frozen** | Hour 6 | OpenAPI committed for all 6 contexts; React app runs fully on mocks. |
| **M2: Scenario 1 green** | Hour 10 | Normal bill auto-pays on Anvil; receipt verifies; cap committed. |
| **M3: Three refusals green** | Hour 12 | Scenarios 2, 3, 4 refuse with reason codes and **zero** transactions. |
| **M4: Escalation green** | Hour 14 | Scenario 5 both ways (valid settles / wrong signature refused). |
| **M5: Second lock + evidence** | Hour 17 | Scenarios 6 and 7 green; all 7 runnable in one script. |
| **M6: Demo understood** | Hour 20 | A non-technical viewer explains a blocked payment without prompting. |
| **M7: Code freeze** | Hour 22 (Sat 15:00) | No commits after; README, `.env.example`, MIT license, video, submission text done. |
| **M8: Demo** | Hour 23 (Sat 16:00) | Demo has run twice from a clean database. |

**Cut line (decided at hour 8, not later):**

| Capability | Classification | If cut, what is lost |
|---|---|---|
| Mandate + Authority + Settlement core | **must** | Nothing works |
| Scenarios 1–7 | **must** | The judging story collapses |
| Evidence verify + anchor (scenario 7) | **must** | Innovation claim weakens |
| Console payer view | **must** | UX criterion (35 pts) suffers |
| Mobile polish, evidence diff view | **should** | Less shine |
| Batched anchoring for non-demo envelopes | **should** | More chain writes |
| PDF invoice extraction | **stretch** | Fixtures instead |
| Constitution version diff UI | **stretch** | Drop silently |

---

*Canonical: `.pi/architecture/implementation-roadmap.md`*
*Last updated: 2026-11-13*