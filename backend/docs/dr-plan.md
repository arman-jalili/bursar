# Bursar DR Plan (demo scope)

## Scope

This is a testnet demo, not a production service. The plan covers the two things that can end the
demo: local state loss and chain/network unavailability.

| Target | Value |
|---|---|
| **RTO** | 10 minutes (restore from snapshot or re-seed) |
| **RPO** | 5 minutes (SQLite snapshot cadence during the demo) |

## What is durable

- `PaymentRouter` and its state (nullifiers, allowlist, caps) — immutable on-chain; survives every
  local failure.
- Rigorix audit envelopes — append-only files in `var/rigorix/.rigorix/audit/`; snapshot them.
- Console and authority SQLite DBs — snapshot every 5 minutes during the demo.
- The HMAC key and operator key — operator environment only; never in the repo.

## Restore

1. Stop the services.
2. Restore `data/*.db` from the latest snapshot. If no snapshot, re-seed and accept the demo
   history loss; the chain still proves settled payments.
3. Restore the audit directory; verify one envelope with the Python SDK.
4. Restart; reconcile reservations against the chain:
   - spent nullifier → committed;
   - unspent and no tx → released;
   - tx pending → ambiguous, poll the receipt.
5. Run the normal-payment scenario once before the demo.

## Chain unavailable

- Switch to Anvil, redeploy the router, re-fund the vault, re-seed. This is a new chain; old
  receipts remain valid only on the old network. Say so.
- If Base Sepolia is unavailable and Anvil is not ready, the demo degrades to the refusal and
  evidence scenes; do not fake a settlement.

## Key loss

- The operator key is in the environment; if lost, redeploy the router with a new operator and
  re-fund. On-chain nullifiers from the old router do not carry over; state that clearly.
- The owner key is a demo key; if lost, rotate it in the mandate and re-sign approvals.

## Post-incident

Record what failed, what was restored, and whether any payment is ambiguous. Never resolve an
ambiguous effect with a guess.


## Billing-specific recovery

See [`docs/dr-plan-billing.md`](dr-plan-billing.md) for the Billing restore/reconcile procedure and the
post-restore invariant queries (`UNIQUE(invoice_hash)`, partial unique index on the active attempt).

## Mandate-specific recovery

Both SQLite files are the whole state; the chain is the other half. A restore is only correct if the
two agree.

| Scenario | Recovery | Verification |
|---|---|---|
| `data/bursar.db` lost | Copy the last backup, then `make db-upgrade DB=console` | `GET /readyz` reports `database: ok` and `Mandate` in `wired_contexts` |
| Lost *after* a settlement | Restore the backup, then reconcile: compare `mandate_payees`/outbox against `PaymentRouter` receipts by nullifier | Settled invoices must not become payable again — the on-chain nullifier is the authority, not the database |
| `data/authority.db` lost | Phase 3 context; until then the reservation ledger is unused | — |
| Partial write suspicion | `PRAGMA integrity_check;` in both files | `ok` |

**Recovery rule:** the database may be stale, the chain may not be replayed. When they disagree, treat
the chain as truth and the database as a cache of it — that is the whole point of the commit-point
lock (ADR-007).

**RPO/RTO for the demo:** RPO = time since last `make backup` (manual, before the demo); RTO = restore
file + restart (< 5 minutes). There is no automatic replication by design: one household, one machine.
