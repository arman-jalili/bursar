# Billing Runbook

**Context:** Billing (supporting subdomain, service depth)
**Hosted by:** `console-api` (`127.0.0.1:8000`), alongside Mandate
**Canonical:** [`.pi/architecture/modules/billing.md`](../.pi/architecture/modules/billing.md)
**Contract:** [`docs/contracts/billing-contract-freeze.md`](contracts/billing-contract-freeze.md)

Everything below is an operator action. Billing never decides whether money may move — it records the
bill and makes the agent's proposal untrusted, structured and non-duplicable before Authority judges it.

---

## 1. Start / stop

```bash
make run-console                      # console-api on :8000 (Billing is installed there)
# or
uv run uvicorn src.apps.console_api.app:app --port 8000
```

Verification after boot:

```bash
curl -s localhost:8000/healthz            # liveness — process is up
curl -s localhost:8000/readyz             # readiness — database + build state
```

`/readyz` must report `database: ok` and `"Billing"` in `build.wired_contexts`. The schema upgrades at
boot; `billing_invoices`, `billing_attempts` and `billing_outbox` exist after `002_billing`.

Shutdown is graceful: stop the process and let in-flight requests finish. Billing's unit of work
commits or rolls back inside the request, so a killed process cannot leave a half-written attempt —
the database either has the attempt **and** the invoice status together, or neither.

---

## 2. The two local invariants that explain most support questions

| Invariant | Symptom | What to do |
|---|---|---|
| **B-3** — one invoice per hash | `POST /v1/invoices` answers `201` with `"duplicate": true` and the **original** invoice id; `DuplicateInvoiceDetected` appears in the outbox | Expected. A replay is not new demand. Do **not** delete the original row to "retry". |
| **B-1** — at most one active attempt | `POST /v1/attempts` answers `409` with `details.status = "in_flight"` | Expected. Inspect the existing attempt; do not force a second one. The partial unique index makes a retry impossible even under a race. |

If the first proposal failed *after* its attempt was created (a refusal), the attempt is `REFUSED` and
the invoice is `OUTSTANDING` again — a fresh proposal is legitimate.

---

## 3. Common incidents

### 3.1 A proposal is rejected with 422 `PROPOSAL_REJECTED`

The payload carried a field Billing does not accept (`payee_address`, `command`, `cap`, `threshold`,
`is_new_payee`, …). This is the ACL working: rejected, not sanitized. The response's
`details.offending_fields` names what was sent. Remove the field; do not add a permissive endpoint.

### 3.2 An invoice presents a mismatching digest (scenario 2)

1. Billing records the invoice anyway — the mismatch is evidence, not a reason to drop the bill.
2. Mandate quarantines the payee; the attempt is refused downstream.
3. Confirm the stored digest is the **presented** one:
   `sqlite3 data/bursar.db "SELECT id,payee_id,presented_digest,status FROM billing_invoices ORDER BY created_at DESC LIMIT 5;"`
4. Confirm the payee's address did **not** change (`mandate_payees`). Billing never routes on the
   document's digest.

### 3.3 An invoice is settled but a proposal still arrives

`409` with `details.status = "settled"` (`InvoiceAlreadySettled`). The settlement is final. A replay of
the same `SettlementConfirmed` delivery is idempotent and writes no second `InvoiceSettled` fact. A
*second* settlement for the same invoice is a bug in Settlement or a duplicate on-chain event — inspect
the receipt; never reopen the invoice locally.

### 3.4 An attempt was denied but the invoice never became payable again

The refusal path is supposed to set the attempt `REFUSED` and the invoice `OUTSTANDING`. Check:

```sql
SELECT i.id, i.status AS invoice_status, a.id AS attempt_id, a.status AS attempt_status
FROM billing_invoices i LEFT JOIN billing_attempts a ON a.invoice_id = i.id
ORDER BY i.created_at DESC LIMIT 10;
```

If the invoice is stuck `IN_FLIGHT` with no non-terminal attempt, the determination handler did not run.
Re-deliver the refusal; the aggregate's terminal rule will not revive the attempt, only free the invoice.

### 3.5 Outbox backlog

```sql
SELECT count(*) FROM billing_outbox WHERE published_at IS NULL;
```

A growing backlog means the dispatcher is not running, not that events were lost. Events are written in
the same transaction as the state (ADR-003). Restart `console-api`; nothing needs to be replayed by hand.

### 3.6 Schema

```bash
make db-upgrade DB=console      # applies 001_mandate then 002_billing (also runs at boot)
make db-downgrade DB=console
```

`002_billing` creates the two storage mirrors of the invariants: `uq_billing_invoices_hash` (B-3) and
the partial unique index `uq_billing_attempts_one_active` (B-1). If either is missing from a running
database, the invariants are only as strong as the application code — upgrade immediately.

---

## 4. Observability

All of this is provided by the shared kernel; Billing adds no bespoke telemetry.

| Signal | Where | What it tells you |
|---|---|---|
| Requests | `GET /metrics` → `bursar_requests_total{route,status}` | Are invoice/attempt calls arriving, and how are they answered? |
| Refusals | `GET /metrics` → `bursar_refusals_total{code}` | How many payments were stopped, by reason (`PROPOSAL_REJECTED`, `AMOUNT_MISMATCH`, …) |
| Latency | `bursar_request_duration_seconds_{sum,count}{route}` | Is the database slow? |
| Structured logs | stdout (JSON when `log_json=true`) | `request.refused` at INFO for a 409; `request.unhandled` for a 500 |
| Correlation | `correlation_id` middleware + error envelope | Tie one console click to every log line |
| Health | `/healthz`, `/readyz` | Liveness vs readiness; `/readyz` also says whether Billing is wired |

Alerting for the demo: a sudden run of `PROPOSAL_REJECTED` is the agent (or a prompt injection) probing
the ACL — that is the product working, but it should be visible.

---

## 5. Contract proofing

```bash
bash .pi/scripts/ci/check_billing_contracts.sh
bash .pi/scripts/freeze.sh verify --module billing
```

The first fails if a frozen interface loses its implementation, a test, a storage mirror or its
composition-root registration. The second proves the module's own invariants (B-1…B-7) still hold.
