# Evidence DR Plan

**Context:** Evidence (`evidence_*` tables in the console database)
**Canonical:** [`.pi/architecture/modules/evidence.md`](../.pi/architecture/modules/evidence.md)
**Companion:** [`docs/dr-plan.md`](dr-plan.md) (whole-demo scope), [`docs/runbook-evidence.md`](runbook-evidence.md)

This is a testnet demo, not a production service. The plan covers what can end the Evidence half of
the demo: losing the local tables, an anchor that cannot be written, and a key that is lost or
exposed.

| Target | Value |
|---|---|
| **RTO** | 10 minutes (restore the SQLite file or re-seal from the publisher outboxes) |
| **RPO** | 5 minutes (snapshot cadence during the demo) |
| **Anchor RPO** | zero after confirmation — the chain is the copy Evidence cannot rewrite |

---

## 1. What is durable

| State | Location | Lost on local failure? |
|---|---|---|
| `evidence_envelopes` (sealed facts) | console SQLite (`data/bursar.db`) | yes — snapshot it |
| `evidence_anchors` (hash → tx) | console SQLite | yes — snapshot it; the chain record survives |
| `evidence_processed_events` (idempotency claims) | console SQLite | yes — snapshot it |
| Envelope hash + tx | Chain (`PaymentRouter.anchor(bytes32)`) | **no** — the independent proof |
| HMAC key | operator environment / secret store | **must be backed up out of band** |
| Publisher outboxes | each context's SQLite | not Evidence's, but the re-seal source |

The database is a **witness log**, not the source of truth for whether a fact happened. The publisher's
outbox and the chain are. When the local envelope table and the chain disagree, the chain proves the
original bytes existed at a point in time. When the local envelope table and the publisher's outbox
disagree, the outbox is what should have been sealed.

---

## 2. Restore

1. Stop `console-api` (graceful; the current unit of work rolls back on kill).
2. Restore the last snapshot of `data/bursar.db` (or copy a known-good file).
3. Apply migrations — a snapshot may predate the Evidence schema:
   ```bash
   make db-upgrade DB=console
   ```
4. Verify the storage mirrors exist:
   ```sql
   SELECT name FROM sqlite_master
   WHERE (type='index'  AND name='uq_evidence_anchors_hash')
      OR (type='trigger' AND name IN (
            'evidence_envelopes_no_update','evidence_envelopes_no_delete',
            'evidence_anchors_no_update','evidence_anchors_no_delete',
            'evidence_processed_events_no_update','evidence_processed_events_no_delete'));
   ```
   Seven rows must be present. If a trigger is missing, stop: E-5 is unenforced.
5. Verify readiness:
   ```bash
   curl -s localhost:8000/readyz   # status: ready, database: ok, Evidence in wired_contexts
   ```
6. Reconcile against the chain and the publisher outboxes (section 3) before trusting the table.

---

## 3. Reconciliation after restore

### 3.1 Envelopes the chain proves

```sql
SELECT id, envelope_hash, event_type, occurred_at
FROM evidence_envelopes ORDER BY occurred_at DESC LIMIT 50;
```

For each envelope:

| Chain / outbox state | Correct local state | Action |
|---|---|---|
| Hash anchored, envelope row present, HMAC verifies | `VERIFIED` | Nothing to do |
| Hash anchored, envelope row present, HMAC fails | `HMAC_MISMATCH` | Treat as tampering; preserve both rows; never repair in place |
| Hash anchored, envelope row missing | gap | Re-seal from the publisher outbox; the hash will differ if the payload differs — investigate before re-anchoring |
| No anchor, envelope row present | `UNANCHORED` | Re-run `write_anchor`; it is idempotent by hash |
| No anchor, no envelope, outbox has the fact | missing witness | Seal the outbox fact once (`(event_id, "seal")` dedupes) |

### 3.2 Claims without envelopes

A claim and its envelope are written in one transaction. A claim without an envelope means somebody
deleted a row outside the application (the trigger would have rejected an `UPDATE`/`DELETE`). Treat it
as an integrity incident: the fact will never re-seal because the claim says it was handled. Restore
from a snapshot or insert the envelope from the outbox and re-verify its hash against the chain.

### 3.3 The HMAC key

The MAC does not record which key produced it. Keep a versioned key log out of band:

| Situation | Action |
|---|---|
| Key still available | Re-run verification; no data change |
| Key lost | Historical envelopes become unverifiable locally. The chain still proves the hash existed. Record the loss; do **not** re-seal old facts with a new key under the old ids |
| Key exposed | Rotate the key, preserve the old key offline for auditing, and treat every envelope sealed with it as suspect until reviewed. Never log the key (E-9) |

---

## 4. Loss scenarios

| Scenario | Recovery | Verification |
|---|---|---|
| `data/bursar.db` lost **before** any anchor | Re-seal from the publisher outboxes; nothing on-chain to reconcile | `evidence_envelopes` grows; `GET /readyz` ready |
| `data/bursar.db` lost **after** anchors exist | Restore the snapshot, then reconcile every hash against the chain (3.1). Envelopes the chain proves must be restored; facts with no chain proof can be re-sealed | Anchored hashes in the restored table match the chain |
| Partial write suspicion (`database disk image is malformed`) | `sqlite3 data/bursar.db "PRAGMA integrity_check;"`; if not `ok`, restore the snapshot | The seven mirrors from section 2 step 4 exist |
| Anchor writer unavailable | `SealEvidence` still appends the envelope and returns `witness_gap`; dispatch is unaffected (E-10) | `UNANCHORED` count returns to zero after the writer recovers |
| Duplicate envelope for one fact | Not possible: `(event_id, "seal")` is the claim and the append is in the same transaction | `SELECT event_id, count(*) FROM evidence_processed_events GROUP BY event_id HAVING count(*) > 1;` returns no rows |
| Duplicate anchor for one hash | Not possible under `UNIQUE(envelope_hash)`; if it happened, the index was dropped by hand | Recreate `uq_evidence_anchors_hash`; audit the extra row before deleting |

Invariant checks after any restore:

```sql
-- E-4: one claim per (event_id, handler). The primary key enforces it; this query is the proof.
SELECT event_id, handler, count(*) FROM evidence_processed_events
GROUP BY event_id, handler HAVING count(*) > 1;

-- E-8: one anchor per hash.
SELECT envelope_hash, count(*) FROM evidence_anchors
GROUP BY envelope_hash HAVING count(*) > 1;

-- E-5: tampering attempts are visible in the logs; the triggers themselves never delete a row.
SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'evidence_%_no_%';
```

The first two queries must return **no rows**; the third must return six triggers.

---

## 5. Post-incident

Record: what was restored, which envelope hashes were reconciled against the chain, whether any HMAC
key was lost or exposed, and which facts were re-sealed. Never resolve an ambiguous envelope by
editing it — the append-only triggers exist precisely so that the answer stays "append a correction
linked by `previous_hash`".
