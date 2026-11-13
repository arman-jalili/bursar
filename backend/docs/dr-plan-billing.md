# Billing DR Plan

**Context:** Billing (`billing_*` tables in the console database)
**Canonical:** [`.pi/architecture/modules/billing.md`](../.pi/architecture/modules/billing.md)
**Companion:** [`docs/dr-plan.md`](dr-plan.md) (whole-demo scope), [`docs/runbook-billing.md`](runbook-billing.md)

This is a testnet demo, not a production service. The plan covers what can end the Billing half of the
demo: losing the local tables, a partial write, and an outbox that stops draining.

| Target | Value |
|---|---|
| **RTO** | 10 minutes (restore the SQLite file or re-seed) |
| **RPO** | 5 minutes (snapshot cadence during the demo) |

---

## 1. What is durable

| State | Location | Lost on local failure? |
|---|---|---|
| `billing_invoices` | console SQLite (`data/bursar.db`) | yes — snapshot it |
| `billing_attempts` | console SQLite | yes — snapshot it |
| `billing_outbox` (unpublished events) | console SQLite | yes — snapshot it |
| Settled payment / nullifier | `PaymentRouter` on-chain | no — the chain is the authority |
| Evidence envelopes | `.rigorix/audit/` (Rigorix) | no if the directory is snapshotted |

The database is a **cache of facts**, not the source of truth. When the database and the chain disagree
about whether an invoice was paid, the chain wins; that is the whole point of the settlement lock.

---

## 2. Restore

1. Stop `console-api` (graceful; the current transaction rolls back on kill).
2. Restore the last snapshot of `data/bursar.db` (or copy a known-good file).
3. Apply migrations — a snapshot may predate the Billing schema:
   ```bash
   make db-upgrade DB=console
   ```
4. Verify the schema mirrors exist:
   ```sql
   SELECT name FROM sqlite_master
   WHERE type='index' AND name IN ('uq_billing_invoices_hash','uq_billing_attempts_one_active');
   ```
   Both rows must be present. If the partial unique index is missing, stop: B-1 is unenforced.
5. Verify readiness:
   ```bash
   curl -s localhost:8000/readyz   # status: ready, database: ok, Billing in wired_contexts
   ```
6. Reconcile against the chain (section 3) before accepting traffic.

---

## 3. Reconciliation after restore

```sql
SELECT id, payee_id, status, amount_micro_usdc, due_date
FROM billing_invoices
WHERE status IN ('in_flight','received','outstanding')
ORDER BY created_at DESC;
```

For each invoice:

| Chain state | Correct database state | Action |
|---|---|---|
| Nullifier spent, receipt confirmed | `billing_invoices.status = 'settled'`; attempt `settled` | Re-deliver `SettlementConfirmed`; `SettleInvoiceService` is idempotent and will not write a second fact |
| No tx, nullifier unspent | invoice `outstanding`, attempt `refused` | Re-deliver the refusal determination; a fresh proposal is then allowed |
| Tx pending | leave `in_flight` / `dispatched` | Poll the receipt; do not guess |

Never mark an invoice settled from a database row alone. The settled event carries the transaction hash
that makes the claim checkable.

---

## 4. Loss scenarios

| Scenario | Recovery | Verification |
|---|---|---|
| `data/bursar.db` lost **before** any settlement | Re-seed the demo data; Billing is empty demand again | `GET /readyz` is ready; `billing_invoices` count > 0 after seeding |
| `data/bursar.db` lost **after** a settlement | Restore the backup, then reconcile with the chain (section 3). Invoices the chain proves paid must be settled; invoices with unspent nullifiers must be payable again | Compare `InvoiceSettled.tx_hash` in `billing_outbox` with the receipt |
| Partial write suspicion (`database disk image is malformed`, inconsistent counts) | `sqlite3 data/bursar.db "PRAGMA integrity_check;"`; if not `ok`, restore the snapshot | The two README invariants as SQL: one row per hash, at most one non-terminal attempt per invoice |
| Outbox stops draining | Restart `console-api`; events are already committed with their state | `SELECT count(*) FROM billing_outbox WHERE published_at IS NULL;` decreases |
| Duplicate invoice row appears | Not possible under the unique index; if it did, the index was dropped during a manual migration | Recreate `uq_billing_invoices_hash`; merge/delete the newer row only after the audit review |

Invariant checks after any restore:

```sql
-- B-3: exactly one invoice per hash.
SELECT invoice_hash, count(*) FROM billing_invoices GROUP BY invoice_hash HAVING count(*) > 1;
-- B-1: at most one non-terminal attempt per invoice.
SELECT invoice_id, count(*) FROM billing_attempts
WHERE status NOT IN ('refused','settled') GROUP BY invoice_id HAVING count(*) > 1;
```

Both queries must return **no rows**.

---

## 5. Post-incident

Record: what was restored, which invoices were reconciled, and whether any settlement is ambiguous.
Never resolve an ambiguous payment with a guess — leave it `in_flight` and let the chain settle the
question.
