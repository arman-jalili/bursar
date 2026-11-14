# Console Runbook

**Context:** Console (generic subdomain, adapter depth — no domain layer, ADR-008)
**Hosted by:** `console-api` (`127.0.0.1:8000`)
**Canonical:** [`.pi/architecture/modules/console.md`](../.pi/architecture/modules/console.md)
**Contract:** [`docs/contracts/console-contract-freeze.md`](contracts/console-contract-freeze.md)

The console **composes**, it does not decide. It projects other contexts' state onto two human
surfaces (owner and payer) and forwards exactly one write — the owner's EIP-712 signature. If the
console is down, no money moves and nothing upstream is lost; the surfaces are simply unavailable.
That is the whole operational story, and it is why this runbook is short: there is no state of its
own to repair.

---

## 1. Start / stop

```bash
make run-console                      # console-api on :8000, installs Mandate/Billing/Settlement/Evidence/Console
# or
uv run uvicorn src.apps.console_api.app:app --port 8000
```

Verification after boot:

```bash
curl -s localhost:8000/healthz        # liveness — process is up (no DB, no chain)
curl -s localhost:8000/readyz         # readiness — database + build state
curl -s localhost:8000/openapi.json   # the eight frozen console routes
```

`/readyz` must report `database: ok` and `"Console"` in `build.wired_contexts`. The console has **no
tables and no migration of its own**; the database readiness check is for the contexts it hosts.

Shutdown is graceful: stop the process and let in-flight requests finish. The console holds no
write-ahead state; its only write is a passthrough request to Authority, which either completed or
did not.

### Upstream transport (demo vs production)

`build_deps()` composes the six ports over `httpx` adapters. By default the adapters use the
**recorded upstream transport** (`src/console/infrastructure/transport.py`), so the demo and CI run
without Authority on `:8001`. A production composition injects the real `httpx` transport instead.
This is a transport choice, not a contract change: the ACL narrows both identically.

---

## 2. Configuration

The console reads the shared settings (`BURSAR_*`); it adds no secret of its own.

| Variable | Effect on the console |
|---|---|
| `BURSAR_CONSOLE_DATABASE_URL` | Database for the hosted contexts' read models (`data/bursar.db` by default) |
| `BURSAR_ENV` | Log format/level defaults |
| `BURSAR_LOG_LEVEL`, `BURSAR_LOG_JSON` | Structured logging (JSON in CI) |
| `BURSAR_PRECONDITION_URL` | Upstream Authority predicate used by the enforcement contexts, not by the console |

Demo credentials (ADR-005 scope map, `src/console/interfaces/deps.py`):

| Token | Scopes |
|---|---|
| `demo-owner-token` | `authority:read`, `authority:sign`, `console:read`, `evidence:read`, `mandate:read` |
| `demo-payer-token` | `console:read`, `billing:read` |
| `demo-agent-token` | `billing:propose`, `billing:read`, `authority:evaluate` — **cannot sign, cannot read the owner surfaces** |

---

## 3. The contract rows that explain most support questions

| Row | Symptom | What to do |
|---|---|---|
| **CON-01** whitelist | An upstream key appears on a screen | Contract breach: the surface whitelist was edited, or a caller bypassed `drop_model_output`. Compare `src/console/infrastructure/acl.py`; never widen a whitelist to fix a demo. |
| **CON-02** exact fields | The owner sees a lowercased address or a rounded amount | Stop the demo. The screen no longer matches the signed bytes; the refusal that follows would look like the owner's fault. Check for a formatter added between the ACL and the DTO. |
| **CON-03** passthrough | Authority rejects a signature the wallet produced | The console forwarded something other than the received bytes. Check the proxy/log: `Content-Type` and the body must be verbatim; the handler reads `request.body()`. |
| **CON-04** read-only | A path tries to create an intent/attempt/settlement | Not a console failure — there is no such route. If the OpenAPI shows one, the route table was edited; redeploy from review. |
| **CON-05** payer copy | "USDC", "gas", "wallet" appears on a payer screen | Copy regression. Fix `application/presentation.py`; the payer-copy suite greps for it. |
| **CON-06** simulated payout | A settled bill reads "Paid" without the demo label | Projection bug or an upstream settlement missing `payout_simulated`. The console raises `PayoutNotLabelled` (409) rather than showing a real transfer. |
| **CON-07** refusal reason | A blocked payment shows a raw code or a generic "failed" | An unknown/missing reason code. The console fails closed (`UnknownReasonCode`/`RefusalReasonMissing`); ask Authority for the closed code. |
| **CON-08** verify toggle | The evidence view says "verified" twice | The console is not proxying Evidence's verdict. Check `EV-*`; the console never computes a second opinion. |
| **CON-09** no domain layer | `src/console/domain/` appears | Architecture violation, not a refactor. Revert; `check_console_contracts.sh` fails the build. |

---

## 4. Common incidents

### 4.1 `401 missing bearer token`

The request has no `Authorization: Bearer <token>` header. The console checks scopes before any
projection runs. Use the demo token for the surface (`demo-owner-token` for approvals/payees/
constitution/evidence, `demo-payer-token` for bills).

### 4.2 `403 FORBIDDEN` — "lacks the <scope> scope"

The token is valid but does not carry the scope for that route. This is the auth matrix working, not
a bug: a payer token can never reach `POST /v1/console/approvals/{id}/signature`
(`authority:sign`), and the agent token cannot read the owner inbox.

### 4.3 `409 CONFLICT` from a console refusal

A projection refused to render a row that would break a contract. The message names the violated
row, e.g.:

- `a settled payer bill must carry payout_simulated: true ...` → upstream settlement is missing the
  demo flag (CON-06).
- `Evidence did not return a verdict ...` / an unrecognised verdict → Evidence is down or answered a
  shape the console does not know (CON-08). The console does not invent a verdict; retry after
  Evidence recovers.
- `client-error` on the passthrough → Authority refused the signature. The response carries the
  household-language reason derived from the closed reason-code set (CON-07); the console shows the
  reason, never the raw code.

### 4.4 Empty payer list

The console composes Billing + Settlement. An empty list means Billing returned no invoices for the
token's scope — not a console cache problem (the in-process cache is TTL-bounded and never
enumeration-capable). Check Billing's `/v1/invoices` with the same token.

### 4.5 A bill stays "Being paid"

`IN_FLIGHT` is Billing's status; the console renders it. The settlement receipt arrives from
Settlement (`GET /v1/receipts/{invoice_id}`). Check Settlement before touching the console.

### 4.6 Owner approval is the only write

If a merchant page or the agent tries to "approve", it will get 403/404. There is no console endpoint
that creates an intent, attempt or settlement order; the owner signature is forwarded to Authority,
and Authority decides.

---

## 5. Observability

The console uses the shared kernel; it adds no bespoke telemetry.

| Signal | Where | What it tells you |
|---|---|---|
| Requests | `GET /metrics` → `bursar_requests_total{route,status}` | Which surface is being hit and how it answers |
| Refusals | `bursar_refusals_total{code}` | 409s — CON-06/CON-07/CON-08 refusals are expected outcomes, not incidents |
| Latency | `bursar_request_duration_seconds_{sum,count}{route}` | Upstream (Authority/Billing/Settlement/Evidence) slowness |
| Logs | JSON with `correlation_id` | One id per request, echoed as `X-Request-Id`; sufficient to trace an approval end-to-end |
| Health | `/healthz`, `/readyz` | Liveness vs database readiness plus the honest build-state list |

**A refusal is not an incident.** `409` responses are counted separately so the demo can show
"refused > 0" without paging anyone.

---

## 6. What not to do

- Do not add a `src/console/domain/` package (CON-09 / ADR-008). If a rule is missing, it belongs in
  Authority, Mandate, Billing, Settlement or Evidence — not here.
- Do not "fix" a mismatched address or digest in the console. Byte fidelity is the contract (CON-02).
- Do not parse or re-serialise the signature body to make a test pass (CON-03).
- Do not make the payer screen explain crypto. Household language only (CON-05).
- Do not let a settled bill render without `payout_simulated` (CON-06).
