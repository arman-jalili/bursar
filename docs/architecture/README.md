# Architecture

Bursar is a modular monolith with two deployables — `console-api` (browser-facing) and
`authority-service` (the enforcement lock) — over one SQLite file in the demo. Each bounded context
owns its aggregates, application services and HTTP surface; cross-context communication is through
ports and events, never another context's tables.

Source docstrings point at these files with a `Canonical:` line. If a rule changes, the document
changes first.

## Decisions

| ADR | Decision |
|---|---|
| [ADR-001](decisions/ADR-001-architecture-pattern.md) | Architecture pattern: modular monolith, two deployables, context boundaries |
| [ADR-002](decisions/ADR-002-data-storage-strategy.md) | Storage: SQLite WAL for the demo, per-deployable split in production, integer micro-units |
| [ADR-003](decisions/ADR-003-cross-context-communication.md) | Cross-context communication: ports, events, transactional outbox |
| [ADR-004](decisions/ADR-004-api-design.md) | API design: frozen HTTP contracts, one error envelope, scopes |
| [ADR-005](decisions/ADR-005-authentication-authorization.md) | Authentication and authorization: owner, agent and settlement scopes |
| [ADR-006](decisions/ADR-006-cost-tracking-usage-metering.md) | Cost from receipts only, never a competing balance |
| [ADR-007](decisions/ADR-007-compliance-engine-architecture.md) | The compliance engine is the decision, not a simulation |
| [ADR-009](decisions/ADR-009-runtime-wiring-multilang-judgment.md) | Runtime wiring: what is wired, and why the write path is governed by Rigorix |

## Modules

| Context | Contract |
|---|---|
| [Mandate](modules/mandate.md) | Household, constitution versions, payees, eligibility, owner proof |
| [Billing](modules/billing.md) | Invoices, attempts, duplicates and one-active guards |
| [Authority](modules/authority.md) | Intents, determinations, cap ledger, approvals, EIP-712 recovery |
| [Settlement](modules/settlement.md) | Orders, nullifiers, receipts, chain gateway, Rigorix adapter |
| [Evidence](modules/evidence.md) | HMAC envelopes, anchors, verify and tamper |
| [Console](modules/console.md) | The browser read models and the signature passthrough |

## Diagrams

- [System context](diagrams/system-context.md) — actors, trust boundaries, deployment view.
- [System overview](diagrams/system-overview.md) — contexts and their ports.
- [Event flow](diagrams/event-flow.md) — the happy path, the refusal path and the events.

## Roadmap

[Implementation roadmap](implementation-roadmap.md) records the build order and the phase gates the
repository grew through.
