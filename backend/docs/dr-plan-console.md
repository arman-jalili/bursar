# Console DR Plan

**Context:** Console (stateless read-model composition; **no tables of its own**)
**Canonical:** [`.pi/architecture/modules/console.md`](../.pi/architecture/modules/console.md)
**Companion:** [`docs/dr-plan.md`](dr-plan.md) (whole-demo scope), [`docs/runbook-console.md`](runbook-console.md)

The console has the best recovery story in the system: it owns no persistent state. Its read models
are projected on demand from the contexts it hosts plus Authority, and its only write is a
passthrough to Authority. Recovery is therefore **restart**, not restore — unless a hosted context's
database is also lost, in which case its own DR plan applies.

| Target | Value |
|---|---|
| **RTO** | < 1 minute (stateless restart); 10 minutes if a hosted context's SQLite file must be restored first |
| **RPO** | zero for console state (nothing to lose); the hosted contexts' plans define theirs |
| **Signature RPO** | zero after Authority accepts it — Authority/Evidence own the durable record, not the console |

---

## 1. What is durable

| State | Location | Lost on local failure? |
|---|---|---|
| Console read models | computed per request | yes — irrelevant; re-projected on the next request |
| In-process TTL cache | process memory (`InMemoryReadModelCache`) | yes — intended; TTL is the only expiry rule |
| Owner signature | Authority (and Evidence's sealed envelope) once forwarded | **no** — the console is a transport, not a store |
| Hosted contexts' tables (Mandate/Billing/Settlement/Evidence) | console SQLite (`data/bursar.db`) | see each context's DR plan |
| Demo bearer tokens | in-process scope map (`interfaces/deps.py`) | yes — redeploy restores them |

The cache deliberately has **no enumeration and no `clear()`** (CON-01/CON-02). A cache that could be
dumped would be a second store of upstream truth; a restart is the supported way to empty it.

---

## 2. Restart (normal recovery)

1. Start the deployable: `make run-console`.
2. Verify readiness:
   ```bash
   curl -s localhost:8000/readyz   # status: ready, database: ok, Console in wired_contexts
   ```
3. Smoke the two surfaces:
   ```bash
   curl -s -H "Authorization: Bearer demo-owner-token" localhost:8000/v1/console/approvals
   curl -s -H "Authorization: Bearer demo-payer-token" localhost:8000/v1/console/bills
   ```
4. Smoke the only write (a dry refusal is fine — Authority must answer):
   ```bash
   curl -s -X POST -H "Authorization: Bearer demo-owner-token" \
     -H "Content-Type: application/json" \
     --data '{"signature":"0x","intent_id":"intent-1"}' \
     localhost:8000/v1/console/approvals/ap-1/signature
   ```
   A `granted` or a household-language refusal both prove the passthrough path is alive. A `409`
   naming a missing reason code means Authority returned an unencoded refusal — see the runbook.

No replay or rebuild step exists, by design: there is nothing to reconcile.

---

## 3. When a hosted context's database is lost

The console reports `database: unavailable` (503 on `/readyz`) and every projection that calls a
port will fail; `healthz` stays `ok`. This is a **hosted context** incident:

1. Follow the affected context's DR plan (`dr-plan-billing.md`, `dr-plan-settlement.md`,
   `dr-plan-evidence.md`; Mandate is part of the whole-demo plan).
2. Restore `data/bursar.db` or start a fresh one and run `make db-upgrade DB=console`.
3. Restart `console-api`; the console itself needs no restore step.

---

## 4. Failover

The demo runs **one** `console-api` instance because the contexts it hosts share a local SQLite file.
The console layer is stateless and would scale horizontally; the hosted contexts would not without
moving off SQLite. Do **not** put two `console-api` instances behind a load balancer on the demo
database — the signature passthrough would still be correct, but the in-process read models could
disagree about a settlement that just landed.

If the console must be replaced during a demo:

1. Start a second instance only after stopping the first (single-writer SQLite).
2. Point the React app at the new base URL (`:8000` in the demo script).
3. Re-run the section 2 smoke.

---

## 5. Upstream Authority outage

The recorded demo transport means the console can render its surfaces without a live Authority. If a
production composition is used and Authority is down:

- Reads that need Authority (`GET /v1/console/approvals`, and any refusal-reason lookup) return a
  transport failure. There is no stale-data fallback: showing an old approval as pending is worse
  than showing an error, because the owner might sign it.
- The only write returns an error; nothing was authorised. Retry after Authority recovers. The
  signature is single-use and expiring, so ask the owner to sign again if the approval expired —
  never reuse a captured body across approvals (the console does not, and must not, repair one).

---

## 6. Secrets and keys

The console adds no secret of its own. The shared HMAC key and settlement key belong to the contexts
the deployable hosts; a leaked or lost key is their incident, not the console's. Demo bearer tokens
are not secrets and are replaced by a real token store before any non-demo deployment.

---

## 7. Post-recovery checks

| Check | Expected |
|---|---|
| `GET /healthz` | `status: ok` |
| `GET /readyz` | `status: ready`, `database: ok`, `Console` in `wired_contexts` |
| `GET /openapi.json` | exactly the eight `/v1/console/*` paths |
| `GET /metrics` | requests increasing; `bursar_refusals_total` may be non-zero (expected) |
| Owner inbox | `payee_address` / `bank_digest` byte-identical to Authority's intent |
| Payer bills | settled rows carry `payout_simulated: true` and the demo label |
| Evidence toggle | untouched envelope `verified`; one flipped byte `tampered` |
