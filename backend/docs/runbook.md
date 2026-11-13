# Bursar Runbook (24-hour demo)

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
