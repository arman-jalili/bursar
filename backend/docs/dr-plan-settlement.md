# Settlement — Disaster Recovery Plan

**Module:** Settlement (Lock 3 — the commit-point lock)
**Canonical:** [`.pi/architecture/modules/settlement.md`](../.pi/architecture/modules/settlement.md)
**Runbook:** [`docs/runbook-settlement.md`](runbook-settlement.md)
**ADR:** [ADR-002 (storage)](../.pi/architecture/decisions/ADR-002-data-storage-strategy.md),
[ADR-003 (outbox)](../.pi/architecture/decisions/ADR-003-cross-context-communication.md),
[ADR-009 (runtime wiring)](../.pi/architecture/decisions/ADR-009-runtime-wiring-multilang-judgment.md)
**Last updated:** 2026-11-14

---

## 1. What must not be lost

Settlement's durable state is four SQLite tables in the `console` database
(`BURSAR_CONSOLE_DATABASE_URL`), plus the chain itself.

| Data | Table | Why losing it is unacceptable |
|---|---|---|
| The write-ahead tx hash | `settlement_orders.tx_hash` | Losing it after broadcast means a restart cannot re-poll — and the tempting recovery is to sign again, which pays twice (SC-3) |
| Spent nullifiers | `settlement_nullifiers` | Losing one re-opens a settled invoice to a replay (SC-5, scenario 6) |
| Chain receipts + cost | `settlement_receipts` | The only input to `CostSummary`; losing rows under-reports spend (SC-10, ADR-006) |
| Outbox facts | `settlement_outbox` | Authority learns commit/release from these; losing one strands a reservation (ADR-003) |

The chain is the **authority of record** for a confirmed settlement. The database is a cache of facts
the chain already holds — except for the tx hash before the receipt exists, which is the one thing the
database knows and the chain cannot be asked about cheaply.

---

## 2. Targets

| Metric | Target | Rationale |
|---|---|---|
| **RPO** (max data loss) | ≤ 5 minutes | one household, low write rate; a 5-minute SQLite snapshot bounds rework to a handful of orders |
| **RTO** (time to service) | ≤ 15 minutes | restore file + `alembic upgrade head` + boot; no second node to promote |
| **Chain RPO** | 0 for confirmed settlements | the chain is not ours to lose; re-poll recovers |
| **Nullifier RPO** | 0 | a lost marker is re-derivable from `orders.nullifier` (same deterministic keccak) — see §5 |

This is a single-household demo deployment (ADR-001: one process, one database file). There is no
multi-region claim and this plan does not pretend otherwise.

---

## 3. Backup strategy

| What | How | When | Retention |
|---|---|---|---|
| `console` SQLite file | `sqlite3 data/bursar.db "VACUUM INTO 'backups/bursar-$(date -u +%Y%m%dT%H%M%SZ).db'"` | every 5 minutes (cron) | 7 days hourly + 30 days daily |
| Migrations | they are in git (`migrations/versions/003_settlement.py`) | on commit | forever |
| Contract + ADRs | git (`docs/contracts/`, `.pi/architecture/`) | on commit | forever |
| Chain receipts | re-readable from the chain by `tx_hash` | on demand | chain-dependent |

`VACUUM INTO` (not `cp`) is deliberate: it takes a consistent snapshot of a WAL database while writers
continue, and it produces a file that is already compacted. `cp` of a live WAL file can capture a torn
page plus a missing `-wal`.

Never back up `settlement_private_key`: it is operator-held configuration (`BURSAR_SETTLEMENT_PRIVATE_KEY`),
rotated out-of-band, and a backup is one more place it can leak.

---

## 4. Restore procedure

```bash
# 1. Stop the service (SIGTERM; the lifespan disposes the pool).
kill -TERM "$(pgrep -f 'src.apps.console_api.app')"

# 2. Pick the newest snapshot and restore it into place.
cp backups/bursar-<timestamp>.db data/bursar.db
rm -f data/bursar.db-wal data/bursar.db-shm   # stale WAL from the dead file would be replayed

# 3. Bring the schema to head (idempotent; never downgrades).
make db-upgrade

# 4. Boot and verify.
make run-console
curl -s localhost:8000/readyz | jq '.checks.database, .build.pending_contexts'
curl -s localhost:8000/v1/orders -H 'Authorization: Bearer demo-owner-token' | jq '.count'
```

Verification after restore:

1. `GET /readyz` → `database: ok`.
2. `GET /v1/orders?status=submitted` → every row has a `tx_hash`. **Re-poll those hashes; do not
   re-sign.** (Until DispatchPayment is wired this set is empty, but the rule is the rule.)
3. `GET /v1/orders?status=pending` → re-poll until finality, then reconcile.
4. `GET /v1/receipts?day=<restore day>` → `cost.total_fee_micro_usdc` matches the last known value.
5. `GET /v1/nullifiers/{value}` for each recently settled invoice → `spent: true` with the right order.
6. Outbox: unpublished `settlement_outbox` rows are re-delivered by the publisher; dedupe is
   `(event_id, handler)` (ADR-003 at-least-once).

---

## 5. Recovering the nullifier set

The nullifier is deterministic: `keccak256(invoiceIdentity || householdScope)` (`Nullifier.derive`). If
`settlement_nullifiers` is lost but `settlement_orders` survives, the set is rebuilt from the orders:

```sql
-- The marker is already on the order; the nullifier table is the lock, not the source of truth.
SELECT nullifier, id AS order_id FROM settlement_orders WHERE status IN ('submitted','pending','confirmed');
```

Insert each pair into `settlement_nullifiers` before accepting traffic. If **both** tables are lost,
recover from the chain: `PaymentRouter.spentNullifiers` is the on-chain copy (SC-6), and any invoice not
in that map was never settled.

---

## 6. Failover

There is no hot standby (ADR-001). The failover plan is *restore, not promote*:

1. Provision the same host (or a clone) with the same `BURSAR_*` configuration.
2. Restore the newest snapshot (§4).
3. Point DNS/ingress at it.
4. Re-poll every `submitted`/`pending` order's persisted hash.

The chain is unaffected by our outage: a transaction broadcast before the failure is still mined. The
only dangerous failure window is **between broadcast and persisting the hash**, which SC-3 exists to
eliminate; with the frozen `ChainGateway` port it cannot be eliminated (blocker B-1 in ADR-009), which
is exactly why dispatch is not wired yet.

### Chain-side incidents

| Incident | Detection | Response |
|---|---|---|
| Reorg removes a receipt | confirmation count drops on re-poll; receipt status flips | the order stays `PENDING` until the network's threshold is met again; never commit a cap early (SC-7) |
| `PaymentRouter` revert | receipt status `REVERTED` + reason | terminal: record `SettlementReverted`, release the reservation, **never retry** (SC-6/SC-8) |
| RPC unavailable | submit/receipt read raises | fail closed; the persisted hash lets a later process re-poll. Do not sign a replacement |
| Wrong network configured | `ChainNetwork.for_chain` raises `UnknownNetwork`; chain id mismatch | refuse. There is no default network on purpose (SC-11) |

---

## 7. Drill schedule (demo readiness)

| Drill | Frequency | Pass criterion |
|---|---|---|
| Restore from a 5-minute snapshot into a clean dir | weekly | `/readyz` ok and `GET /v1/orders` count matches the source |
| Rebuild the nullifier table from orders | weekly | a known settled invoice still reports `spent: true` |
| Kill the process after `mark_submitted` (integration, when dispatch lands) | before demo | restart re-polls the same hash; no second tx (SC-3) |
| Replay a settled invoice through the API | before demo | `409 duplicate_settlement`, zero transactions (SC-5, scenario 6) |
| Direct contract replay of a spent nullifier (Anvil) | before demo | contract reverts; app records `SettlementReverted` (SC-6) |

The last three are the module's actual safety claim. Until the chain adapter and the contract exist
(ADR-009 gaps G-1/G-2), only the app-side half can be drilled.
