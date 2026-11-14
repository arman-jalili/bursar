# ADR-001: Domain-Driven Design with Bounded Contexts (Python Modular Monolith)

**Status:** Accepted
**Date:** 2026-11-13
**Session:** 432050ea-0419-44ba-8ac4-b239242634b4

## Context

The domain exploration identified six bounded contexts that must stay independently
evolvable while sharing one process, one database file and one 24-hour build window:

- **Mandate** (core) — household, parties, payees, constitution versions
- **Authority** (core) — payment intents, determinations, cap ledger, approvals
- **Settlement** (core) — dispatch, PaymentRouter, receipts, nullifiers
- **Billing** (supporting) — invoices, payment attempts
- **Evidence** (supporting) — HMAC envelopes, anchors, verification
- **Console** (generic) — read models and UI composition

Hard constraints from the business context: host language **Python**, no LLM in the
enforcement path, the authority service must be a separate process from the agent's
writable workspace, and Rigorix OSS `rigorix-server` is used unmodified.

## Decision

We will use **DDD with bounded contexts implemented as a modular monolith in Python**
(FastAPI + SQLAlchemy 2.0), where:

1. Every context is a top-level package under `src/<context>/` with four layers:
   `domain/`, `application/`, `infrastructure/`, `interfaces/`.
2. `domain/` imports no framework, no ORM, no HTTP — pure Python plus the shared kernel.
3. Contexts communicate **only** through published domain events and narrow ports;
   no context reaches into another context's `domain/` or `infrastructure/`.
4. **Authority runs as its own FastAPI process** (`authority-service`) separate from the
   agent workspace. This is not microservices-for-its-own-sake: it is a security boundary
   required by NFR-003 (the agent must not be able to write policy or reservations).
5. Enforcement is **not** a context: Rigorix preconditions + `PaymentRouter.sol` sit
   outside the model as infrastructure that Authority and Settlement call.

Dependency direction between contexts follows the context map:

```
Console ──▶ Authority ──▶ Mandate
   │            │  ▲         ▲
   │            ▼  │         │
   └───────▶ Evidence  Settlement ──▶ (chain)
                ▲            │
                └────────────┴── Billing ──▶ Mandate
```

## Consequences

- Each context owns its tables (`<context>_*` prefix) and its domain logic; no shared tables.
- Cross-context reads go through ports/read models, never through foreign repositories.
- Mandate is a pure upstream: it is imported by four contexts, so it must stay stable and
  free of any knowledge of payments.
- Authority is a conformist to Mandate: it re-reads constitution and payee eligibility at
  dispatch time and never caches, which keeps the "moment of consequence" rule honest.
- Two deployables (`authority-service`, `console-api`) instead of one — the split is the
  security claim, and it costs an extra process to run locally.
- Any future extraction to real microservices is a package-to-service move, not a rewrite.

## Alternatives Considered

| Alternative | Pros | Cons | Reason Rejected |
|---|---|---|---|
| Single-process monolith, all contexts in one FastAPI app | Fastest to build | Agent process could reach reservations and policy; breaks NFR-003 | Rejected — the security boundary is the product |
| Microservices per context (6 services) | Clean isolation | 6 deployables, 6 DBs, service mesh, 24h budget blown | Rejected — over-engineering for one household |
| Layered monolith without bounded contexts | Familiar | Enforcement logic leaks into billing; invariants unenforceable | Rejected — no separation of consequence |
| Rigorix-only (no authority service, rules in TOML) | Fewest moving parts | Rigorix cannot know "payee eligible" or reserve capacity atomically | Rejected — see ADR-007 |

## Affected Modules

- `docs/architecture/modules/mandate.md`
- `docs/architecture/modules/billing.md`
- `docs/architecture/modules/authority.md`
- `docs/architecture/modules/settlement.md`
- `docs/architecture/modules/evidence.md`
- `docs/architecture/modules/console.md`

## Related ADRs

- ADR-002 (storage), ADR-003 (events), ADR-005 (auth), ADR-007 (enforcement engine)