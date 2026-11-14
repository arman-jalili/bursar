# Bursar

**A household account where an automation proposes payments, the owner's rules decide, and Rigorix
enforces at the moment of payment.** USDC settles on Anvil; every attempt — allowed or refused —
leaves a signed envelope the owner can verify in the browser.

> **Watch the 3-minute pitch:** [Bursar demo on Loom](https://www.loom.com/share/3e83df3ef2f14d78af4dabf808134a04) ·
> [shot list and narration](docs/bursar-pitch-script.md).

Proximata Hackathon '26 · track *Bringing Crypto to Everyday Life*.

This repository is **not a click-through mock**. The approval card signs a real EIP-712-shaped
digest, Authority verifies it, Settlement signs a real transaction, Rigorix's governed
`run_command` broadcasts it, and `PaymentRouter.sol` moves USDC exactly once. Capacity is not
claimed by the proposal path: the gate's own check claims it inside the governed run, immediately
before the send.

The UI tells the story in two capabilities:

- **Capacity** — ask for a €20 bill on a €30 cap. It runs. Ask for €11 with €10 left: Rigorix still
  runs the governed step, its capacity check refuses at the moment of sending, and the refusal is a
  signed envelope with the finding. Signed, never sent.
- **Precondition** — an approval is a request, not a durable grant. Sign a €20 payment above a €15
  approval line, then freeze that payee as the operator. At the moment of sending Rigorix re-reads
  the payee authority and refuses. The owner approved; the gate still stops it. The owner can also
  **reject** the request: the decision is recorded, nothing is signed, nothing is sent.

---

## Quick start (Docker)

**Prerequisites:** Docker Engine / Docker Desktop with Compose v2, ~8 GB free disk (the governed
execution image compiles `rigorix-server` once), and internet for the first image build. No
OpenRouter key is required — without one the console uses a local regex parser.

```bash
# 1. Configuration. `.env` is gitignored; `.env.demo` already holds the public demo keys.
cp .env.example .env
#    Optional: put an OpenRouter key in BURSAR_LLM_API_KEY (https://openrouter.ai/keys).

# 2. Install the operator's dispatch checks OUTSIDE the repo (this is the point).
#    The containerized Rigorix reaches Authority by service name:
BURSAR_GATE_URL=http://authority:8001 ./scripts/setup-preconditions.sh

# 3. Build the governed execution host once (rigorix-server + the Bursar broadcaster).
./scripts/build-rigorix-image.sh

# 4. Start the stack.
docker compose --profile container-rigorix up -d --build

# 5. Open the gate.
open http://localhost:5173/#capacity
open http://localhost:5173/#precondition
```

Optional, for the on-chain view the video shows:

```bash
docker compose -f explorer/blockscout/anvil.yml -p bursar-explorer up -d
open http://localhost:4000
```

The app links to it: **USDC wallet ↗** opens the token page (holders are the treasury and each
payee), **explorer ↗** opens the index, and every transaction hash in a gate card links to its
transaction page. The explorer is read-only and does not change how the gate behaves.

### Ports

| URL | What | Exposure |
|---|---|---|
| `:5173` | the UI (nginx-served SPA) | browser |
| `:8000` | console API + chat agent | browser (CORS allow-list) |
| `:4000` | Blockscout (optional) | browser |
| `:8001` | authority service | keep private |
| `:8545` | Anvil JSON-RPC | keep private |
| `:3001` | Rigorix JSON-RPC | internal (service DNS) |

### After changing configuration

- Changed `.env` values used by the console (LLM, Rigorix URL): `docker compose up -d console`.
- Changed the checks or the gate URL: rerun `setup-preconditions.sh`, then
  `docker compose restart rigorix` (the host reads the file at boot).
- Full reset (chain redeploys, ledger and trail restart): `docker compose down -v`, then start
  again. The checks live in `/tmp/bursar-preconditions` and survive.

## The two demos

Both pages stage their own world on load and **apply & reset** is the explicit reset. Loading a
page stages its cap/approval line without deleting an approval or a hold made by the other page; a
page refresh starts a fresh evidence chain.

**Capacity** (`/#capacity`)

1. "pay the energy bill 20" → **PAID**, free capacity drops to €10, the transaction links to the
   explorer.
2. "pay energy 11" → **NOT SENT**. Rigorix's capacity check failed (exit 3), the card shows the
   finding, and the trail holds the signed envelope.
3. **Verify in browser** checks the HMAC and the envelope schema in WebCrypto; expand the JSON to
   see the findings and their digests.

**Precondition** (`/#precondition`)

1. "pay energy 20" on a €30 cap with a €15 approval line → **NEEDS YOUR APPROVAL**.
2. Freeze **Wien Energie** in *The world* panel (the operator's authority is a file outside the
   repo).
3. **Sign & send**: the browser signs the intent digest, Authority grants, and Rigorix refuses the
   send on the payee check — **STOPPED BY RIGORIX**. Verify the envelope. Nothing was broadcast.
   Or press **Reject**: the request closes, nothing is signed, and the decision is recorded.

## What runs

| Layer | Process | What it does |
|---|---|---|
| Chain | Anvil `:8545` | `TestUsdc` + `PaymentRouter` deployed by `backend/scripts/deploy_contracts.py`; the operator is funded and approved. |
| Execution host | `rigorix-server` `:3001` (OSS, **unmodified**) | The governed `run_command` step (`payments.broadcast`) and the HMAC-signed audit envelope. |
| Authority | `authority-service` `:8001` | Re-reads the constitution and payee eligibility, decides allow/deny/escalate, and answers the gate's approval/capacity/audit reads. |
| Settlement | `console-api` `:8000` (Settlement context) | Reads the verdict live, signs locally, persists the hash **before** broadcast, asks Rigorix to send it. |
| Lock 3 | `PaymentRouter.sol` | Nullifier once-only, EIP-712 owner signature, amount/address frozen on the signed intent, `Anchored` event. |
| Owner surface | `console-api` `:8000` `/v1/console/*` | Approvals, bills, constitution, payees, evidence verdicts; one write — the signature passthrough. |
| Agent + gate | `console-api` `:8000` `/v1/agent/*` | Natural-language payment proposals (LLM), the capacity gate, the dispatch-precondition switch, and the chained trail. |
| UI | `frontend` `:5173` | Two capabilities with browser HMAC verification. |
| Explorer | Blockscout `:4000` (optional) | Indexes the same Anvil chain: USDC token page, every transaction, the `Anchored` log. |

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
both against one SQLite file so Authority's reads see Mandate/Billing writes immediately;
production keeps the per-deployable split.

Rigorix runs three operator-owned checks **inside** the governed step, in this order, all fail
closed:

1. **approval-valid** — above the line, does the intent carry the owner's verified signature?
2. **payee-authorized** — is the payee still `active` in the operator's `authority.json`?
3. **capacity-available** — does the amount still fit today's cap, and may it claim the units?

A non-zero exit refuses the step and still produces a signed envelope with
`precondition_findings[]` (`outcome`, `exit_code`, `check_digest`, `authority_digest`,
`check_writable`). The checks and the authority file live outside the repository, which is the
point.

More: [`docs/README.md`](docs/README.md) · [`docs/architecture/`](docs/architecture/) (ADRs,
module contracts, diagrams) · [`docs/contracts/`](docs/contracts/) (frozen behavioural contracts).

## OpenRouter and the parser

The chat box is parsed by an LLM when a key is present. The amount always comes from the sentence,
and every downstream check is deterministic.

```bash
# .env
BURSAR_LLM_API_KEY=sk-or-v1-...
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=nvidia/nemotron-3.5-lightning:free
LLM_FALLBACK_MODEL=inclusionai/ling-3.2-flash:free
```

- Get a key at <https://openrouter.ai/keys>.
- Free models are rate-limited upstream; the fallback model covers that. Any OpenAI-compatible
  provider works by changing `LLM_BASE_URL` and the model names.
- No key: the local regex parser handles "pay energy 20" and the full gate demo still runs.
- The key is read by `console-api` only and is never baked into the frontend.

The full variable list, with the server-deployment values (public console/explorer URLs, CORS), is
in [`.env.example`](.env.example).

## Running on a server

The quick start is already the server shape: Rigorix runs in its own container. For a public host,
bake the browser-facing URLs and allow the origin:

```bash
PUBLIC_CONSOLE_URL=https://demo.example.com:8000 \
PUBLIC_EXPLORER_URL=https://demo.example.com:4000 \
  docker compose --profile container-rigorix up -d --build
```

```bash
# .env
BURSAR_CORS_ORIGINS=https://demo.example.com
```

Expose `5173`, `8000` and (optionally) `4000`. Keep Anvil, Authority and Rigorix private: the
authority has no CORS on purpose, and an open Anvil RPC accepts unsigned transactions.

For k3s, see [`deploy/k8s/README.md`](deploy/k8s/README.md). The manifests target a single node
(RWO volumes); a multi-node cluster needs a shared filesystem or the per-deployable databases
ADR-002 describes.

## Development

```bash
cd backend
make install          # uv venv + dev dependencies
make test             # the full suite (912 tests, one geometry skip)
make lint             # ruff
make typecheck        # mypy
```

The backend is Python 3.12 (FastAPI + SQLAlchemy async + SQLite WAL). The frontend is React + Vite:

```bash
cd frontend
npm install
npm run build
```

For the local demo loop, the containerized Rigorix is the simplest path. The alternative is a
host-run `rigorix-server`:

```bash
cd backend && make install
./scripts/run-rigorix.sh                 # expects a sibling rigorix-oss checkout; sets PATH for the broadcaster
docker compose up -d anvil contracts migrate authority console frontend
./scripts/setup-preconditions.sh         # default gate URL http://127.0.0.1:8001
```

## Repository layout

```
frontend/                 React + Vite: capacity (Gate.tsx) and precondition (Precondition.tsx)
backend/
  src/apps/               console-api and authority-service composition roots
  src/apps/console_api/agent.py   chat agent, gate, authority switch, release/reject, trail
  src/shared/             config, SQLite/WAL, error envelope, health
  src/mandate/            household, constitution, payees, eligibility
  src/billing/            invoices, attempts, duplicate and one-active guards
  src/authority/          intents, determinations, cap ledger, approvals, EIP-712 recovery
  src/settlement/         orders, nullifiers, receipts, chain gateway, Rigorix adapter
  src/evidence/           HMAC envelopes, anchors, verify/tamper
  src/console/            the frozen browser read models + signature passthrough
  contracts/src/          PaymentRouter.sol and TestUsdc.sol
  scripts/                deploy_contracts.py, seed_demo.py
  tests/                  unit + integration (912 tests)
docs/
  architecture/           ADRs, module contracts, diagrams, roadmap
  contracts/              frozen behavioural contracts (A/S/R/E/SC invariants)
  bursar-pitch-script.md  shot list and narration for the 3-minute demo (video on Loom)
scripts/                  build-rigorix-image.sh, run-rigorix.sh, setup-preconditions.sh
explorer/blockscout/      the independent Blockscout stack over the same Anvil chain
deploy/k8s/               single-node k3s manifests
docker-compose.yml        anvil, contracts, migrate, authority, console, frontend (+ container-rigorix)
.env.demo                 public Anvil/test values only
.env.example              the optional parser key and deployment variables
```

## Demo keys (public test values — never mainnet)

All keys in `.env.demo` are public Anvil test keys and are unsafe on any real network:

- owner: Anvil account `0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266`
- settlement operator: Anvil account `0x70997970C51812dc3A010C7d01b50e0d17dc79C8`
- bearer tokens: `demo-owner-token`, `demo-agent-token`

## What is real, what is simulated

| Real | Simulated / labelled |
|---|---|
| Owner signature over the exact intent digest, recovered by Authority | The demo owner key is Anvil account 0 (a public test key), signed in the browser. |
| Authority allow/deny/escalate, capacity ledger, single-use approval, rejection | — |
| Two-phase settlement: sign → persist hash → governed broadcast | Finality polling (`SettleOnce`) is not wired; a broadcast order is shown Paid. The Anvil transaction is mined. |
| Rigorix `run_command` + HMAC audit envelope, verified in the browser | Authority's outbox events are not replicated into the Evidence projection; the UI verifies the Rigorix envelope directly. |
| `PaymentRouter` nullifier + on-chain owner signature + `Anchored` event | The last mile to a fiat bank account is simulated and labelled. |
| USDC on Anvil | Base Sepolia is the production claim; the demo uses Anvil. |

## Known gaps

- The Settlement finality poller is not wired; orders stop at `submitted`.
- Evidence envelopes are not relayed from the outboxes into the Evidence projection.
- SQLite means a single node; the k3s manifests assume one node with RWO volumes.
- Free OpenRouter models can be rate-limited; the fallback model and the local parser keep the demo
  answering.

## License

MIT — see [LICENSE](LICENSE).
