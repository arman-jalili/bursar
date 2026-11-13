# ADR-002: Data Storage Strategy (SQLite + SQLAlchemy per Context)

**Status:** Accepted
**Date:** 2026-11-13

## Context

The blueprint default is Postgres + SQLx per context. That is a Rust-shaped default and
it does not fit this project:

- Host language is **Python** (SQLx is Rust-only; the equivalent is SQLAlchemy 2.0 / aiosqlite).
- The business context mandates **SQLite for the authority service** explicitly.
- The timebox is 24 hours. A Postgres container plus migrations plus connection pooling is
  hours of setup that buys nothing at one-household scale.
- The demo must run from a clean checkout on a laptop with no paid dependency (NFR-008).

What the domain genuinely needs from storage is narrow but strict:

1. **Atomic cap reservation** — `committed + reserved <= cap` must hold under concurrency
   (scenario 4: six split invoices).
2. **Exactly-once settlement bookkeeping** — a nullifier is spent once (scenario 6).
3. **Append-only evidence** — envelopes are never mutated (scenario 7).
4. **Durable, ordered domain events** — nothing silently dropped.

## Decision

Use **SQLite with WAL enabled**, one database file per deployable, with **SQLAlchemy 2.0
(async) + Alembic** migrations. Schema is namespaced per context by table prefix:

| Context | File | Table prefix |
|---|---|---|
| Authority | `data/authority.db` | `authority_*` |
| Console + Mandate + Billing + Settlement + Evidence | `data/bursar.db` | `mandate_*`, `billing_*`, `settlement_*`, `evidence_*`, `console_*` |

Rules:

- **One aggregate = one transactional boundary.** An application service opens exactly one
  transaction; no cross-aggregate transaction except where an invariant demands it.
- **Cap reservation is one conditional UPDATE**, not read-then-write:
  `UPDATE authority_cap_ledger SET reserved = reserved + :amt WHERE day = :d AND committed + reserved + :amt <= cap`.
  Zero rows affected means refuse. This is what makes scenario 4 pass under concurrency.
- **Ports live in `domain/`, adapters in `infrastructure/`** — the dependency-inversion arrangement
  (Evans' repository / Fowler's PoEAA): the domain declares the persistence contract it needs
  (`find_in_force`, `save`), the adapter fulfils it. The arrow is `infrastructure → domain`, never the
  reverse, and ADR-008's `interface-ownership` gate fails the build for a `tactical` module whose
  `infrastructure/` adapter has no `domain/`-owned `Protocol`/`ABC`.
  Repositories return **aggregates**, never rows, so the ORM stays outside the model.
  *Considered and rejected:* declaring the ports in `application/` (hexagonal-books' reading, where
  the use cases own them). It is a defensible pattern, but here the persistence contract is part of
  the aggregate's published language — `find_in_force` exists because of invariant H-4, not because of
  a use case — and moving it would put a persistence concern in the layer that should be free of one
  while gaining nothing the gate can check.
- Domain objects are never ORM-mapped directly — a mapper in `infrastructure/` translates
  between the domain aggregate and the table row.
- Events are persisted in an `*_outbox` table in the same transaction that produces them
  (see ADR-003).
- WAL + `busy_timeout=5000` + a single writer connection for the ledger; reads may use
  additional connections.

## Consequences

- Zero external infrastructure; the whole system runs from `make demo`.
- Postgres-specific types are unavailable: use `TEXT` for ids/hashes, `INTEGER` for USDC
  micro-units (never floats), ISO-8601 `TEXT` for timestamps.
- Write concurrency is serialized. That is a **feature** here: the cap ledger wants
  serialization, and one household will never exceed it.
- Migrating to Postgres later is a dialect change plus a data copy; the domain layer is
  unaffected because it does not know the database exists.

## Alternatives Considered

| Alternative | Pros | Cons | Reason Rejected |
|---|---|---|---|
| Postgres + SQLAlchemy per context | Production-shaped, real concurrency | Container, pooling, setup hours, over-scope | Rejected — 24h budget, one household |
| Postgres + SQLx (blueprint default) | Fast, Rust-native | SQLx is Rust; project is Python | Rejected — wrong language |
| In-memory + JSON files | Trivial | Atomic cap check impossible; nothing durable for evidence | Rejected — breaks scenarios 4, 6, 7 |
| SQLite without WAL / without conditional UPDATE | Simple | Lost-update race lets split invoices through | Rejected — breaks invariant behind scenario 4 |

## Affected Modules

- All six module docs; storage detail appears under each module's `Components` section.

## Related ADRs

- ADR-003 (event outbox uses the same transaction)
- ADR-007 (cap reservation is a precondition the enforcement layer depends on)