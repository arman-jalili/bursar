# Bursar

**A household account where an automation proposes payments, the owner's rules decide, and Rigorix
enforces at the moment of payment.** USDC settles on Anvil; every payment leaves a receipt the owner
can verify in the browser.

> **On the word "agent".** This repository has no agent process today: a token exists
> (`demo-agent-token`) and the seed script acts as the proposer. Either point a real proposer at the
> API (see `docs/demo-ux.md` §2, option A) or read the copy as "an automation proposes". The demo
> must not claim a component it does not ship.

Proximata Hackathon '26 · track *Bringing Crypto to Everyday Life*.

This repository is **not a click-through mock**: the approval card signs a real EIP-712-shaped
digest, Authority verifies it and reserves capacity, Settlement signs a real transaction,
Rigorix's governed `run_command` broadcasts it, and `PaymentRouter.sol` moves USDC exactly once.

The page is about the gate, in two capabilities:

- **Capacity** — ask the agent to pay. With a €30 cap, €20 runs through and the next €11 is refused
  before anything is signed.
- **Precondition** — an approval is a request, not a durable grant. The owner signs a €20 payment on
  a €30 cap with a €15 approval line; the operator then freezes that payee; the release is refused at
  **dispatch time** by Rigorix's own precondition, with a signed finding and no transaction.

---

## What runs

| Layer | Process | What it does |
|---|---|---|
| Chain | Anvil `:8545` | `TestUsdc` + `PaymentRouter` deployed by `scripts/deploy_contracts.py`; the operator is funded and approved. |
| Lock 1 | `rigorix-server` `:3001` (OSS, **unmodified**) | The governed `run_command` step (`payments.broadcast`) and the HMAC-signed audit envelope. |
| Lock 2 | `authority-service` `:8001` | Re-reads the constitution and payee eligibility, decides allow/deny/escalate, reserves capacity. |
| Settlement | `console-api` `:8000` (Settlement context) | Reads the verdict live, signs locally, persists the hash **before** broadcast, asks Rigorix to send it. |
| Lock 3 | `PaymentRouter.sol` | Nullifier once-only, EIP-712 owner signature, amount/address frozen on the signed intent, `Anchored` event. |
| Owner surface | `console-api` `:8000` `/v1/console/*` | Live approvals, bills, constitution, payees, evidence verdicts; one write — the signature passthrough. |
| Agent + gate | `console-api` `:8000` `/v1/agent/*` | Natural-language payment proposals (LLM), the capacity gate, the dispatch-precondition switch, and the signed-envelope trail. |
| UI | `frontend` `:5173` | Two capabilities: **capacity** (`/#capacity`) and **precondition** (`/#precondition`), with browser HMAC verification and a chained trail. |

## Quick start (this machine)

```bash
# 0. The agent's parser key (gitignored .env). OpenRouter is the default provider.
#    BURSAR_LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / LLM_FALLBACK_MODEL

# 1. Core services (anvil, contract deployment, migrations, authority, console, UI)
docker compose up -d --build anvil contracts migrate authority console frontend

# 2. Rigorix (OSS host). It runs beside the repo and needs the backend venv on its PATH.
./scripts/run-rigorix.sh

# 3. Arm the dispatch-time precondition (check + operator authority live outside the repo)
./scripts/setup-preconditions.sh
# then restart the Rigorix host so it reads .rigorix-runtime/.rigorix/preconditions.toml

# 4. Open the gate
open http://localhost:5173/#capacity
```

The pages set their own world on load: capacity = €30 with every payment inside the cap allowed;
precondition = €30 cap and a €15 approval line. A page refresh starts a fresh evidence chain.

The optional seed (`docker compose run --rm … python scripts/seed_demo.py`) still populates the
classic €500-cap world through the public APIs for the frozen console read models.

### Dispatch-time precondition

`scripts/setup-preconditions.sh` installs an operator-owned check in `/tmp/bursar-preconditions/`
and an `authority.json` keyed by payee address (`active` / `frozen`). Rigorix runs that check after
any approval and immediately before `payments.broadcast`; a non-zero exit refuses the step. The
refusal still produces a signed audit envelope with `precondition_findings[]` (`outcome`, `exit_code`,
`check_digest`, `authority_digest`, `check_writable`). The console only reads and writes that status
file as the operator's switch (`GET/POST /v1/agent/authority`); the check and the authority live
outside this repository, which is the point.

The optional seed creates one household with a €500 daily cap and a €100 signature line, and produces
real determinations:

- **Wien Energie €84.20** — eligible, inside the cap → *allowed*, dispatched through Rigorix.
- **Apotheke €48.50** — presented bank digest does not match → *quarantined*, refused.
- **Zahnarzt €240** — new payee above the line → *escalated*: the approval waits for you.
- **Hausmeister €60** — allowed once, then the payee is frozen → the next decision is refused.

Sign the dentist in the console: the browser signs the intent digest with the demo owner key,
Authority grants and reserves, Settlement signs and persists, Rigorix broadcasts, and the bill turns
**Paid** with its transaction hash.

### Clean reset

```bash
docker compose down -v
docker compose up -d anvil
docker compose up contracts migrate
docker compose up -d --no-deps authority console
# then run the seed again (step 3)
```

## What is real, what is simulated

| Real | Simulated / labelled |
|---|---|
| Owner signature over the exact intent digest, recovered by Authority | The demo owner key is Anvil account 0 (a public test key), signed in the browser. |
| Authority allow/deny/escalate, capacity ledger, single-use approval | — |
| Two-phase settlement: sign → persist hash → governed broadcast | Finality polling (`SettleOnce`) is not wired; a broadcast order is shown Paid. The Anvil tx is mined. |
| Rigorix `run_command` + HMAC audit envelope | Evidence envelopes are not yet relayed into the Evidence projection (the UI drawer shows the console record). |
| `PaymentRouter` nullifier + on-chain owner signature + `Anchored` event | The last mile to a fiat bank account is simulated and labelled. |
| USDC on Anvil | Base Sepolia is the live claim; the demo uses Anvil. |

## Architecture

```
owner (UI) ──signature──▶ console-api ──authority──▶ authority-service
                                     │                    │ allow/deny/escalate
                                     ▼                    ▼
                              settlement: sign + persist hash
                                     │
                                     ▼  run_command (governed)
                              rigorix-server ──▶ payments.broadcast ──▶ PaymentRouter
                                                                          │
                                                                     USDC to payee
```

Two deployables on purpose (ADR-001): `authority-service` is the enforcement lock and is not
reachable from a browser (no CORS); `console-api` is the only browser-facing surface. The demo runs
both against one SQLite file so Authority's read-through sees Mandate/Billing writes immediately;
production keeps the per-deployable split.

## Repository layout

```
frontend/                 React + Vite pages: capacity (Gate.tsx) and precondition (Precondition.tsx)
backend/
  src/apps/               console-api and authority-service composition roots
  src/apps/console_api/agent.py   chat agent, capacity gate, authority switch, release, trail
  src/shared/             config, SQLite/WAL, error envelope, health
  src/mandate/            household, constitution, payees, eligibility
  src/billing/            invoices, attempts, duplicate and one-active guards
  src/authority/          intents, determinations, cap ledger, approvals, EIP-712 recovery
  src/settlement/         orders, nullifiers, receipts, chain gateway, Rigorix adapter
  src/evidence/           HMAC envelopes, anchors, verify/tamper
  src/console/            the frozen browser read models + signature passthrough
  contracts/src/          PaymentRouter.sol and TestUsdc.sol
  scripts/                deploy_contracts.py, seed_demo.py
scripts/run-rigorix.sh    starts the unmodified OSS rigorix-server on the host
scripts/setup-preconditions.sh  installs the operator check + authority outside the repo
docker-compose.yml        anvil, contracts, migrate, authority, console, frontend
.env.demo                 public Anvil/test values only
.env.example              the optional LLM key variables (copy to a gitignored .env)
```

## Demo keys

All keys in `.env.demo` are public Anvil test keys and are unsafe on any real network:

- owner: Anvil account `0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266`
- settlement operator: Anvil account `0x70997970C51812dc3A010C7d01b50e0d17dc79C8`
- bearer tokens: `demo-owner-token`, `demo-agent-token`

## Status / known gaps

- The Settlement finality poller (contract item B-2) is not wired; orders stop at `submitted`.
- Evidence envelopes are not relayed from the outboxes into the Evidence projection yet.
- The containerised Rigorix image (compose profile `container-rigorix`) is experimental; the host
  `scripts/run-rigorix.sh` is the supported demo path because the OSS workspace rebuild is large.
- The LLM parser is convenience only: the amount always comes from the sentence, and a local regex
  parser takes over when the provider is unavailable. Free OpenRouter models can be rate-limited
  upstream; `LLM_FALLBACK_MODEL` keeps the demo answering.

## License

MIT — see [LICENSE](LICENSE).
