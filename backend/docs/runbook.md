# Bursar Runbook (24-hour demo)

## Local CI / tests

The project targets **Python 3.12** (`uv`). The Guardian scripts resolve tools from `PATH`, so on a
machine where a system `pytest`/`ruff` shadows the venv they will report failures that are really
interpreter mismatches:

```bash
make check                                    # canonical: ruff + mypy + pytest via uv
PATH="$PWD/.venv/bin:$PATH" bash .pi/scripts/ci/run_preflight.sh   # harness preflight
```

`tests/conftest.py` raises an explicit error if it is imported by an interpreter older than 3.12.

## Billing context — operational procedures

The Billing runbook (invoices, attempts, duplicate replay, forbidden proposals, settled invoices,
outbox backlog) lives in [`docs/runbook-billing.md`](runbook-billing.md). Billing is hosted by the same
`console-api` process and owns the `billing_*` tables.

## Mandate context — operational procedures

The Mandate context is hosted by **console-api** (port 8000) and owns the `mandate_*` tables in
`data/bursar.db`. Everything below is an operator action, not a developer action.

### Quarantine (automatic, expected)

A payee is quarantined when an invoice presents a bank digest that does not match the verified one.
This is the scam path working, not an incident:

1. Check the evidence trail: `GET /metrics` shows `bursar_refusals_total{code="PAYEE_QUARANTINED"}`.
2. Confirm the payee's stored address did **not** change (it must not):
   `sqlite3 data/bursar.db "SELECT id,name,address,status FROM mandate_payees;"`.
3. If the change is legitimate, the **owner** re-approves with a signed request:
   `POST /v1/payees/{id}/reapprove` with `owner_proof`. No operator can clear quarantine.

### Freeze (owner-initiated, terminal within a mandate)

`POST /v1/payees/{id}/freeze`. There is deliberately no unfreeze endpoint: resuming a payee is a
re-registration with fresh owner proof. If a freeze was a mistake, register the payee again.

### Constitution version published

Versions are append-only and addressable. To audit which rules governed a past decision:

```sql
SELECT number, cap_micro_usdc, threshold_micro_usdc, status, content_hash, published_at
FROM mandate_constitution_versions ORDER BY number DESC LIMIT 5;
```

A `ConstitutionCorrupted` error (HTTP 500) means zero or two versions are `in_force` — a partial
unique index forbids the latter, so check for hand-edited rows before anything else.

### Stale aggregate (HTTP 409 `CONFLICT`)

Two operators changed the same aggregate. Reload (`GET` the record) and retry; do **not** retry
blindly, or the invariant that rejected the first write is defeated.

### Outbox backlog

If `mandate_outbox` grows without `published_at` being set, the dispatcher is not running. Events are
durable, so nothing is lost; restart console-api.

```sql
SELECT count(*) FROM mandate_outbox WHERE published_at IS NULL;
```

### Schema

```bash
make db-upgrade DB=console      # applies 001_mandate (runs at boot too)
make db-downgrade DB=console    # drops mandate_* tables
```

## Start

```bash
docker compose up --build          # Anvil mode by default
# or, locally:
# 1. rigorix-server (workspace: var/rigorix)
# 2. authority-service :8001
# 3. console-api :8000
```

Verify:

```bash
curl -s localhost:8000/healthz
curl -s localhost:8001/healthz
curl -s localhost:3001/health
```

## Demo reset

1. Stop the console and authority service.
2. Delete the demo databases (`data/console.db`, `data/authority.db`) and `var/rigorix/.rigorix/audit/*`.
3. Restart; the scenario loader re-seeds the household, payees, invoices and policy.
4. Confirm the daily cap ledger is zero and the USDC vault has the demo balance.

## Incident: chain unavailable

- Switch `CHAIN=anvil`, restart the console, redeploy `PaymentRouter` via the Anvil make target.
- The UI must show **Local Anvil** instead of Base Sepolia. Say it on stage.
- Do not fabricate a chain receipt. A pending settlement shows `ambiguous` and is reconciled when
  the chain returns.

## Incident: Rigorix server down

- The console refuses to dispatch; attempts show `failed` with a transport error.
- Restart `rigorix-server` from the workspace root with `RIGORIX_SANDBOX=container`.
- Do not bypass the precondition to "keep the demo moving." A demo without the gate is not the
  product.

## Incident: suspected duplicate payment

- Do not retry. Read the on-chain nullifier for the invoice.
- If the nullifier is spent, the invoice is settled; mark the attempt settled and do not resend.
- If unspent and no tx, release the reservation and allow a fresh attempt.
- The contract revert is a refusal, not an error to work around.

## Incident: evidence does not verify

- Confirm the envelope came from `.rigorix/audit/<execution_id>.json`, not a console copy.
- Verify with the Python SDK using the same key as `rigorix.toml audit_hmac_key`.
- If the anchor is present, compare the envelope hash to the on-chain event.
- If a byte was flipped, the failure is the demo working; reset the envelope from the audit file.

## Stop

```bash
docker compose down            # keeps volumes
docker compose down -v         # destroys demo state
```
