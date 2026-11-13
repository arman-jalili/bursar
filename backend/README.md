# Bursar

**A delegated bill-paying agent for a household.** An owner gives an AI agent a mandate to pay a
parent's recurring bills. A machine-enforced constitution and an on-chain second lock make it
impossible for the agent — or a stolen operator key — to pay the wrong payee, exceed the caps, or
pay the same invoice twice.

> *The agent proposes; the code disposes.*

Proximata Hackathon '26 — track *Bringing Crypto to Everyday Life*.

---

## Why this exists

An adult child manages a parent's household bills. The parent should not have to think about due
dates, portals or crypto. The child wants to delegate the work **without** handing over unlimited
authority. The failure modes are concrete and each one is a refusal, not an error:

| Failure mode | What stops it |
|---|---|
| A scam invoice says "our bank details changed" | Bank-digest mismatch → payee quarantined, address unchanged, payment refused |
| The agent splits one payment to dodge a limit | Aggregate daily cap: `committed + reserved ≤ cap`, one atomic UPDATE |
| A payment is approved, then the payee is frozen | Authority re-reads eligibility at dispatch, not at plan time |
| The same invoice is paid twice after a timeout | Nullifier derived from the invoice hash, enforced on-chain |
| A stolen operator key drains the account | EIP-712 signature bound to one exact intent + on-chain commit-point lock |
| Nobody can prove what was allowed or refused | HMAC evidence envelope for every attempt, hash anchored on-chain |

## The three locks

```
Agent proposal
     │
     ▼
① Rigorix (unmodified OSS)    preconditions.toml · sequence-policy.toml · capacity.toml
     │                        → fail closed if the precondition program is unreachable
     ▼
② Authority service (:8001)   re-reads constitution + payee eligibility at this instant
     │                        → allow | deny | escalate, with reason codes
     │                        → atomic reservation against the daily cap
     ▼
③ PaymentRouter.sol           nullifier unspent · EIP-712 signature valid · amount/address match
                              → REVERT is terminal: a refusal, never a retry
```

No LLM appears in any of the three. That is checkable, and a test asserts it.

## Status

**Phase 0 of 7 — bootstrap.** This repository currently contains the shared kernel, both deployable
skeletons, migration tooling and the architecture package. Bounded contexts arrive per
[`.pi/architecture/implementation-roadmap.md`](.pi/architecture/implementation-roadmap.md):

| Phase | Context | Depth | Hours |
|---|---|---|---|
| 0 | Bootstrap | — | 0–1 |
| 1 | Mandate | tactical (core) | 1–4 |
| 2 | Billing | service (supporting) | 4–6 |
| 3 | Authority | tactical (core) | 6–10 |
| 4 | Settlement | tactical (core) | 10–14 |
| 5 | Evidence | service (supporting) | 14–16 |
| 6 | Console | adapter (generic) | 16–20 |

## Quick start

```bash
make install                 # uv venv + editable install
cp .env.example .env         # the demo values work against Anvil as-is
make test                    # shared kernel + both deployables boot
make run-authority           # :8001  enforcement-critical (no CORS)
make run-console             # :8000  browser-facing
make health                  # curl /readyz on both
```

Migration tooling (two databases, one migration tree):

```bash
make db-upgrade DB=console
make db-upgrade DB=authority
```

## Layout

```
src/shared/domain/          shared kernel — Money, ValueObject, AggregateRoot, DomainEvent, Clock
src/shared/infrastructure/  config (pydantic-settings), logging + redaction, SQLite/WAL engine
src/shared/interfaces/      error envelope (ADR-004), /healthz + /readyz
src/apps/authority_service/ composition root, port 8001 (Authority context, Phase 3)
src/apps/console_api/       composition root, port 8000 (everything browser-facing)
src/<context>/              created in each context's own build phase — not yet present
contracts/                  PaymentRouter.sol (Phase 4)
migrations/                 Alembic; 000_bootstrap creates no tables
```

Two deployables on purpose (ADR-001): the agent process must not be able to reach the authority
database or its signing material.

## Design documents

Everything is in `.pi/architecture/`:

| Document | What's in it |
|---|---|
| [implementation-roadmap.md](.pi/architecture/implementation-roadmap.md) | 7 phases, dependency graph, must/should/stretch cut line |
| [decisions/](.pi/architecture/decisions/) | ADR-001…007 — architecture, storage, events, API, auth, cost, **enforcement engine** |
| [modules/](.pi/architecture/modules/) | Per-context aggregates, invariants, python stubs, endpoints, acceptance criteria |
| [diagrams/](.pi/architecture/diagrams/) | System context + trust boundaries, event flow (incl. the refusal path) |
| `.pi/domain/` | Domain exploration: 6 contexts, 25 FR, 18 NFR, 51 ubiquitous-language terms |

Regenerate/inspect the domain model with `/domain --validate 432050ea-0419-44ba-8ac4-b239242634b4`.

## Honest boundaries

- Rigorix enforces the operator's determination; it does not know what "payee eligible" means.
- The bank payout is **simulated and labelled as such**. USDC settlement is real (Base Sepolia);
  the last mile to a fiat bank account is not.
- Local Anvil is a demo convenience; Base Sepolia is the live claim.
- One household, USDC only. No multi-tenancy, no trading, no accounting integration.
- Invoice ingestion is fixtures for the hackathon; PDF extraction is a stretch item.

## License

MIT — see [LICENSE](LICENSE).