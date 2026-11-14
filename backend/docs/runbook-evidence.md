# Evidence Runbook

**Context:** Evidence (supporting subdomain, service depth)
**Hosted by:** `console-api` (`127.0.0.1:8000`), alongside Mandate and Billing
**Canonical:** [`.pi/architecture/modules/evidence.md`](../.pi/architecture/modules/evidence.md)
**Contract:** [`docs/contracts/evidence-contract-freeze.md`](contracts/evidence-contract-freeze.md)

Evidence is a **witness, not a guard**. It seals every delivered fact into a signed envelope and
records the envelope hash on-chain. If Evidence is down, payments still move; the missing witness is
found afterwards with `WitnessReport` (E-10). Nothing in this runbook authorises stopping a payment.

---

## 1. Start / stop

```bash
make run-console                      # console-api on :8000 (Evidence is installed there)
# or
uv run uvicorn src.apps.console_api.app:app --port 8000
```

Verification after boot:

```bash
curl -s localhost:8000/healthz        # liveness — process is up
curl -s localhost:8000/readyz         # readiness — database + build state
```

`/readyz` must report `database: ok` and `"Evidence"` in `build.wired_contexts`. Schema migration
`003_evidence` runs at boot; `evidence_envelopes`, `evidence_anchors` and
`evidence_processed_events` exist afterwards, together with the three append-only triggers.

Shutdown is graceful: stop the process and let in-flight requests finish. Evidence's unit of work
either commits the claim + envelope + anchor together or rolls back; it never leaves a half-sealed
fact.

**Operator-key requirement:** `BURSAR_HMAC_KEY` must be set and non-empty. Without it the signer
refuses to boot (`SigningUnavailable`), because sealing without a key would produce unverifiable
evidence. The key is never stored in a table or printed by the signer (`repr` is redacted; E-9).

---

## 2. The frozen invariants that explain most support questions

| Invariant | Symptom | What to do |
|---|---|---|
| **E-1** canonical bytes | Verification fails for an envelope nobody edited | A payload field changed shape (float, timezone, key order). Compare `canonical_bytes()`; do not "fix" the stored row — append a correction. |
| **E-4** idempotency | The same delivery arrives three times; one envelope exists, two results say `duplicate: true` | Expected. `(event_id, "seal")` is claimed atomically. |
| **E-5** append-only | `UPDATE`/`DELETE` on any `evidence_*` table aborts with `evidence is append-only` | Expected. Record a correction with `EvidenceEnvelope.corrected()`; never edit the sealed row. |
| **E-6** verify OK | `GET /v1/evidence/{id}/verify` → `VERIFIED` + `anchor_tx` | Healthy. |
| **E-7** one flipped byte | `409 HMAC_MISMATCH`, `details.field = "payload"`, `anchor_tx` unchanged/empty | Local tampering (or a bug that edited the row). The anchor is the independent proof; preserve both rows for the audit. |
| **E-8** anchor mismatch | `409 ANCHOR_MISMATCH` naming `envelope_hash` and `anchor_hash` | The envelope points at another proof. Do not re-anchor by force; investigate how the hash was rewritten. |
| **E-9** key isolation | A key value appears in a payload, log or DB column | Security incident. Rotate `BURSAR_HMAC_KEY`, preserve the old key offline for verification of historical envelopes (the MAC does not identify which key sealed it, so keep a key-version log). |
| **E-10** witness-only | `witness_gap` in `SealEvidenceResult`; `unpublished` outbox backlog | Expected during an Evidence outage. Nothing blocks dispatch; run the witness report once Evidence is back. |

---

## 3. Common incidents

### 3.1 An envelope verifies as `HMAC_MISMATCH` (scenario 7)

1. Read the envelope: `GET /v1/evidence/{id}?full=1`.
2. Read its anchor: `GET /v1/evidence/{id}/anchor`.
3. The anchor is unchanged (E-7); the failure is local. Preserve the row and the original request log.
4. If the change came from a legitimate correction, the wrong tool was used. Append a new envelope
   with `previous_hash` pointing at the original hash; never repair the original.
5. If the change was not legitimate, treat it as tampering: the on-chain hash proves the original
   bytes existed at a point in chain time.

### 3.2 `UNANCHORED`

`GET /v1/evidence/{id}/verify` returns `200` with `result: UNANCHORED` when no anchor row exists for
the envelope hash. Re-run the anchor attempt with `SqlAnchorGateway.write_anchor`. It is idempotent
by hash; a second writer cannot create a second row (`UNIQUE(envelope_hash)`).

### 3.3 A publisher was refused because Evidence was down

Evidence must never do that. Check the publisher: a refusal whose reason mentions Evidence is a bug
in the wiring, not intended behaviour. Dispatch continues; seal the backlog from the publisher's
outbox, deduped by `(event_id, "seal")`.

### 3.4 Witness-gap report names facts that exist

```bash
curl -s -H "Authorization: Bearer demo-owner-token" \
  "localhost:8000/v1/evidence?intent_id=intent-42"
```

If the envelope exists but the report says missing, the `evidence_processed_events` row was written
without the envelope (a crash between claim and append). That is impossible inside one unit of work;
check for a manually deleted row and treat it as an integrity incident.

### 3.5 Outbox / dispatcher backlog

Evidence seals facts delivered by the publisher-outbox workers. A growing `*_outbox WHERE
published_at IS NULL` means the dispatcher is not running, not that evidence was lost. Restart the
worker; the subscriber is idempotent.

### 3.6 Schema

```bash
make db-upgrade DB=console      # applies 003_evidence (also runs at boot)
make db-downgrade DB=console
```

`003_evidence` creates the three tables, `uq_evidence_anchors_hash` (E-8) and the
`*_no_update` / `*_no_delete` triggers (E-5). If any trigger is missing, the append-only guarantee is
only as strong as the application code — upgrade immediately.

---

## 4. Observability

Evidence uses the shared kernel; it adds no bespoke telemetry.

| Signal | Where | What it tells you |
|---|---|---|
| Requests | `GET /metrics` → `bursar_requests_total{route,status}` | Verify/list/read traffic and its answers |
| Refusals | `bursar_refusals_total{code}` | `HMAC_MISMATCH` / `ANCHOR_MISMATCH` counts — the console's tampered toggle |
| Latency | `bursar_request_duration_seconds_{sum,count}{route}` | Database or anchor slowness |
| Structured logs | stdout (JSON when `log_json=true`) | `evidence.envelope.sealed`, `evidence.seal.duplicate`, `evidence.witness.gap` |
| Correlation | `correlation_id` middleware + error envelope | Tie one console click to every log line and to the envelope's `event_id` |
| Health | `/healthz`, `/readyz` | Liveness vs readiness; `/readyz` says whether Evidence is wired |

Logs deliberately carry `event_id`, `envelope_id` and `envelope_hash` only — never the payload and
never the HMAC key (E-9).

---

## 5. Contract proofing

```bash
bash .pi/scripts/ci/check_evidence_contracts.sh     # interfaces, adapters, HTTP, triggers, composition root
bash .pi/scripts/ci/stage_evidence_proofing.sh      # the above + suites + real coverage gate
bash .pi/scripts/freeze.sh verify --module evidence # the freeze record (E-1 … E-11)
```

The proofing stage fails if a frozen interface loses its implementation, a trigger disappears, the
router drops an endpoint, or coverage on `src/evidence` falls below 90 %.
