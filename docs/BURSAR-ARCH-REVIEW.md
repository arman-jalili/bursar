# Bursar — architecture review (24-hour override)

**Date:** 2026-11-13
**Verdict:** approve the ADRs. The architecture is **not wrong**; the risk is spending the clock
on optional surface while the three must scenes are not green. Four items are must-fix; the rest
is optional richness. If Guardian generates an optional item at near-zero marginal cost and the
team can test it, keep it — a richer architecture can help the technical score. The rule is risk
to the live demo, not purity.

> Conflict rule: `docs/BURSAR-ARCH-REVIEW.md` + `docs/BURSAR-BUILD-CONTRACT.md` win over the
> generated module/roadmap detail. The generated docs remain the domain map; the must-set below
> is the territory.

## 0. Wrong vs unnecessary vs risky

| Item | Wrong? | Demo-critical? | If built |
|---|---|---|---|
| Public API prefix/shape (`/api` vs `/v1`) | **Yes** — the frontend integrates against one contract | Yes | Integration breaks |
| Evidence as a second HMAC signer | **Yes** if it replaces or obscures Rigorix's envelope | No | Byte-parity bug; false evidence claim |
| Command path `payments.dispatch` vs `payctl` | **Yes** — the step won't match/execute | Yes | Precondition/executor mismatch |
| “Every refusal is enveloped” | **Yes** — false for plan-time denials | — | Judge catches the overclaim |
| 42 endpoints as **internal** module APIs | No | No | Extra code/tests; harmless if not public |
| 42 endpoints as the **public** API | **Yes** — bypass paths and auth surface | No | Authority bypass, demo confusion |
| Transactional outbox ×6 | No | No | Relay/dedupe bugs; debugging time |
| API keys + scopes + payer tokens | No | No | Auth friction; demo lockout |
| Payer view | No | No | Second UI/token; distracts |
| Alembic | No | No | Migration debugging |
| Gas/fee/batching/budget | No | No | Extra code; low risk |

**Generation time is not integration time.** A relay, a second canonical encoder and six outboxes
are moving parts that fail at 2 a.m. That is the only reason to defer them. If they are free and
tested, keep them. The must/should/stretch table in §3 is a **fallback order**, not a prohibition.

## 1. The callouts, classified

### 1.1 One public API, two deployables

**Must-fix for the public surface.** Internal module endpoints are optional; the 11 public
endpoints and the `/api` prefix are not.

The generated module docs define **42 REST endpoints** (Mandate 11, Billing 5, Authority 8,
Settlement 6, Evidence 4, Console 8). That is a distributed monolith and 4–6 hours of routing,
schemas and auth for endpoints the demo never calls.

**Fix:** implement only the **11 endpoints in `docs/BURSAR-BUILD-CONTRACT.md`** as the public
console API at `/api`. The six contexts are **Python modules**, not services.

Deployables:
- `console-api` (`:8000`, prefix `/api`) — the 11 public endpoints, SSE, serves the SPA.
- `authority-service` (`:8001`, prefix `/v1`, internal only) — `POST /v1/precondition/check`,
  `POST /v1/intents`, `POST /v1/settle`, `POST /v1/release`, `GET /healthz`.

The per-context endpoint tables in the module docs are **internal application-service contracts**,
not public REST. ADR-004's public `/v1` is superseded for the MVP; `/v1` survives only as the
authority-service prefix.

The frozen public surface:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | household, policy, mode, capacity, chain |
| GET | `/api/invoices` | invoice list |
| GET | `/api/attempts` | attempt list |
| GET | `/api/attempts/:id` | attempt + envelope + events |
| GET | `/api/attempts/:id/envelope` | raw signed envelope |
| POST | `/api/attempts/:id/approve` | owner signature |
| POST | `/api/attempts/:id/deny` | deny |
| POST | `/api/policy` | owner-only rule change |
| POST | `/api/payees/:id/freeze` | freeze |
| POST | `/api/payees/:id/reverify` | clear quarantine |
| POST | `/api/scenarios/:id` | demo controls |
| GET | `/api/events` | SSE |

### 1.2 Evidence is a verifier, not a second signing engine

**Must-fix if the app envelope replaces or obscures Rigorix's. Optional if it is a separate,
clearly labeled receipt log.** A second HMAC signer is a byte-parity risk; use the SDK.

The generated Evidence module builds a second HMAC envelope pipeline over all 41 domain events
(event subscriber → canonical encoder → signer → append-only store → anchor policy → outbox).
That duplicates Rigorix's signed envelopes, creates a second canonical-encoding surface, and is
the single largest hidden cost in the plan.

**Fix:**
- Evidence **captures Rigorix envelopes** from `.rigorix/audit/<execution_id>.json`, verifies
  them with the Python SDK, stores the record + hash, and optionally anchors the hash on-chain.
- Plan-time denials have **no engine envelope**. Store them as `refusal_records` (attempt, rule
  id, reason, source `console`) and label them "policy refusal — not an engine envelope".
- No event subscriber over the 41-event catalog; no second HMAC signer; no per-event envelope
  store. The browser verifies the Rigorix envelope with `rigorix-verifier/browser`.

### 1.3 No transactional outbox in the MVP

**Optional, not wrong.** Keep it only if generated and tested before G2; otherwise use in-process
events. A relay is a moving part that can fail during the demo.

Six `*_outbox` tables, relays, at-least-once delivery and dedupe are robustness work the demo
cannot afford.

**Fix:** domain events are in-process; state changes and their events are written in one
transaction where needed. The console reads the databases; Evidence reads the Rigorix audit
file. An outbox is a stretch goal, not Phase 0–5 work.

### 1.4 Auth = two demo tokens + EIP-712

**Optional richness.** The minimum is two tokens + EIP-712; scopes and payer tokens are not
demo-critical.

API keys hashed in a table, scope sets, payer tokens, an auth matrix and `AccessDenied` envelopes
are over-scope.

**Fix:** `OWNER_TOKEN` and `AGENT_TOKEN` from env; a FastAPI dependency maps token → role. The
agent token can only propose/read; the owner token can do everything. EIP-712 remains the
consequence authorization. No payer token, no scope table, no key hashing for the demo.

### 1.5 Defer payer view and re-approval

**Optional/deferred.** Not wrong; add after G4 only if free.

The roadmap marks the payer view as **must**; the analyst pruning marks it deferred. It adds a
second UI mode, a second token and copy work. Re-approval adds a recovery flow the demo does not
need.

**Fix:** defer both. The seven-scenario traceability stays; scenarios 5 and 3 do not require the
payer view. If the clock allows after G4, add them.

### 1.6 Alembic is deferred

**Optional.** `create_all` is the fallback; do not debug migrations at 2 a.m.

Six migrations with up/down are not required for a demo.

**Fix:** SQLAlchemy `Base.metadata.create_all` on startup; reset by deleting the demo DB. Keep
the schema documented. Add Alembic only if the team finishes early.

### 1.7 Cost tracking is the cap ledger only

**Optional.** The cap ledger only is enough; the rest is extra.

Gas/fee receipts, a budget guard and anchor batching are not must-haves.

**Fix:** the cap ledger is the single spend truth. The chain receipt records gas; no separate
accounting. Anchor one hash per demo scene; no batching. No budget guard (no LLM in enforcement).

## 2. Corrections to the generated docs

| # | Issue | Correction |
|---|---|---|
| 1 | Report says “34 events for 5 contexts” and “41 events” | The diagram contains **41** (Mandate 12, Billing 7, Authority 12, Settlement 7, Evidence 3). Use 41. |
| 2 | “Every arrow ends in an envelope” | Every **runtime** determination ends in a Rigorix envelope; a plan-time denial is a console record. State it. |
| 3 | `run_command` shown as `payments.dispatch` | The command is `/opt/bursar/bin/payctl --intent <id>`; the structured params ride alongside. Standardize. |
| 4 | Roadmap marks payer view **must** | Deferred. |
| 5 | Roadmap marks all 7 scenarios **must** | Must: 1, 2, 7. Must-if-3+: 3, 5. Should: 4, 6, anchor. See §3. |
| 6 | ADR-004 public `/v1` | Public `/api` per the build contract; `/v1` is the internal authority prefix. |
| 7 | ADR-005 API keys + scopes | Two demo tokens + EIP-712. |
| 8 | ADR-006 gas/fee/batching/budget | Cap ledger only; rest deferred. |
| 9 | ADR-003 outbox | In-process events; outbox deferred. |
| 10 | Phase 0 “Alembic upgrades/downgrades” | `create_all`; Alembic deferred. |
| 11 | Phase 0 “validators green” | Create `docs/runbook.md` and `docs/dr-plan.md` stubs first, or the readiness validator cannot pass. |
| 12 | Module docs define 42 endpoints | Internal contracts only; public surface is the build contract. |

## 3. Revised must / should / stretch

### Must (the submission is eligible only if these are green)

- Scenarios **1** (normal pay), **2** (poisoned invoice refused), **7** (evidence verifies; flip
  a byte fails).
- Six modules scaffolded; console API + authority service boot; composition root wired.
- Rigorix on the dispatch path: one precondition refusal and one plan-time sequence denial.
- USDC settlement on Anvil (Base Sepolia if funded).
- The 3-pane UI with the rule that decided and the receipt.
- README, `.env.example`, MIT license, 3-minute video, written submission.

### Must if 3+ people (adds the innovation score)

- Scenario **5** (EIP-712 approval; wrong signature refused).
- Scenario **3** (freeze after approval; dispatch refusal).

### Should

- Scenario **4** (split invoices; daily cap).
- Scenario **6** (duplicate bypass; contract nullifier).
- On-chain anchor of the envelope hash.
- Hosted URL.

### Stretch / deferred

Payer view, re-approval, outbox, API scopes, Alembic, batched anchoring, LLM agent mode,
passkey, capacity-ledger race, effect-commitment Ambiguous scene.

## 4. Revised critical path (from now)

| Window | Work | Gate |
|---|---|---|
| H+0–H+1 | Apply this override; `/project create`; two services boot; console API skeleton; OpenAPI; mocks | **G0** |
| H+1–H+4 | Mandate + Billing modules; fixtures for 7 scenarios; UI shell on mocks | |
| H+4–H+8 | Authority + cap ledger; Rigorix config; normal pay on Anvil; poisoned refusal | **G2 by H+8** |
| H+8–H+12 | Evidence capture + browser verify; console API wiring; UI integration | **G3** |
| H+12–H+16 | Approval + freeze (if 3+); Base Sepolia; duplicate bypass | **G4** |
| H+16–H+19 | Hosted; polish; scenario buttons; README/.env/MIT | |
| H+19–H+21 | Video; clean run twice; submit | **G5 by 14:30** |

If G2 is not green by **H+8**, cut approval and freeze; focus the remaining time on the normal
payment, the refusal, the evidence verify, and the UI.

## 5. What to keep from the generated architecture

- The seven ADRs' decisions, with the scope corrections above.
- The six contexts and their invariants; the 41-event catalog as the **domain map**, not as an
  implementation checklist.
- Authority as a separate process by security design.
- SQLite WAL; the cap invariant as one conditional `UPDATE`.
- EIP-712 off-chain + on-chain agreement; the invoice nullifier.
- The 36 acceptance criteria as a menu; implement the ones attached to the must scenarios.
- OpenAPI-first, but published by **H+2**, not H+6; the frontend starts on mocks immediately.

## 6. First gate (H+4)

- `src/console/app.py` and `src/authority/app.py` exist and boot.
- `check_composition_root.sh` green: the console app imports/registers all six modules.
- `validate-ubiquitous-language.sh` green (src exists).
- The public API matches the 11 endpoints; the SPA runs on mocks.
- A plan with `/bin/echo` executes through Rigorix on the dev machine.
- `docs/runbook.md` and `docs/dr-plan.md` stubs exist so readiness is not red.

If this gate is red at H+4, the plan is wrong — cut, do not add.
