# Settlement — Runbook

**Module:** Settlement (Lock 3 — the commit-point lock)
**Canonical:** [`.pi/architecture/modules/settlement.md`](../.pi/architecture/modules/settlement.md)
**Contract:** [`docs/contracts/settlement-contract-freeze.md`](contracts/settlement-contract-freeze.md)
**Runtime decision:** [ADR-009](../.pi/architecture/decisions/ADR-009-runtime-wiring-multilang-judgment.md)
**Last updated:** 2026-11-15

---

## 1. What runs today

| Surface | State | Where |
|---|---|---|
| Domain (aggregate, value objects, domain services) | **Implemented** — the 80 frozen contract suites plus the 25 chain tests are green (`pytest tests/unit/settlement`) | `src/settlement/domain/` |
| Persistence (orders, nullifiers, receipts, outbox) | **Implemented** — migration `003_settlement`, 7 SQLite integration tests | `src/settlement/infrastructure/` |
| Read API (`GET /v1/orders`, `/v1/orders/{id}`, `/v1/orders/{id}/receipt`, `/v1/receipts?day=`, `/v1/nullifiers/{value}`) | **Live** in `console-api` | `src/settlement/interfaces/http/router.py` |
| `POST /v1/intents/{intent_id}/dispatch` | **Live** — Authority gate (SC-1) + Rigorix `run_command` (SC-2), composed at startup | `src/settlement/application/dispatch.py`, `src/settlement/infrastructure/{authority,rigorix}/` |
| `PaymentRouter.sol` + chain adapter (`ChainGateway`) | **Built, not deployed** — `prepare`/`broadcast`, receipts, nullifier reads; 31 tests end to end against `eth-tester` | `contracts/src/`, `src/settlement/infrastructure/chain/` |
| `payments.broadcast` (the governed broadcast step) | **Live as a console script** — sends one already-signed transaction, nothing else | `src/settlement/infrastructure/chain/broadcast_cli.py` |
| `POST /v1/anchors` | **`501`** — the adapter exists but no router is deployed; the message names it | `src/settlement/interfaces/http/router.py` |
| `DispatchPayment` | **Live** — gate → sign → persist hash + bytes (`signed`) → governed broadcast → `SUBMITTED` | `src/settlement/application/dispatch.py` |
| `SettleOnce` | **Not wired** — blocked on re-freeze (B-2) | `src/settlement/application/services.py` |
| `PaymentRouter.sol` | **Built, not deployed** — solc 0.8.24, nullifier map, EIP-712 owner check, `Anchored` event; 11 pytest tests on an in-process EVM (no `forge`/`anvil` here) | `contracts/src/PaymentRouter.sol` |
| `Web3ChainGateway` (chain adapter) | **Built** — `prepare`/`broadcast`/receipt/nullifier reads, EIP-1559 signing, refusals instead of traces | `src/settlement/infrastructure/chain/` |
| Rigorix `run_command` adapter | **Live** — one module-constant command per order, `execution_id = order.id`, the step's error surfaced verbatim | `src/settlement/infrastructure/rigorix/command_adapter.py` |

A dispatch today does exactly five things, in this order:

1. reads the determination **live** from Authority (SC-1);
2. **signs locally** (`ChainGateway.prepare`) — the tx hash is known and nothing is on the wire;
3. persists the order **with the hash and the signed bytes**, status `signed` (SC-3), and commits;
4. runs the one fixed Rigorix `run_command`, which is `payments.broadcast --raw-tx <hex>` (SC-2) — the
   governed step sends the bytes that were already signed and recorded;
5. marks the same hash `submitted`.

The response carries `tx_hash` = the hash that was signed, and `status: "submitted"` when the governed
step accepted the bytes. If the step refuses, the order keeps its hash and stays **`signed`**: a real
state meaning "signed, not broadcast", recovered by re-sending those same bytes (a node-level replay of
one transaction — one nonce), never by dispatching again: the intent already has an order, so a second
dispatch is a `409 duplicate_settlement` (SC-4).

---

## 2. Startup

Settlement is a context inside `console-api`; it has no separate process.

```bash
make install                 # uv venv + editable install
make db-upgrade              # alembic -x db=console upgrade head (runs 003_settlement)
make run-console             # uvicorn src.apps.console_api.app:app --port 8000
```

Dependencies:

| Dependency | Required by | Failure mode if missing |
|---|---|---|
| `console` SQLite file (`BURSAR_CONSOLE_DATABASE_URL`) | every endpoint | `/readyz` reports `database: error`; boot runs migrations first |
| PostgreSQL/Redis | nothing in Settlement | not used |
| Rigorix `rigorix-server` (default `:8080`; the verified local host was `:3001`) | dispatch | dispatch answers `409` naming the transport reason; reads unaffected |
| Authority service (the `BURSAR_PRECONDITION_URL` origin) | dispatch | dispatch answers `409` — the gate fails closed (SC-1), never "allowed" |
| A reachable RPC node + `BURSAR_SETTLEMENT_PRIVATE_KEY` | dispatch (the gateway is not built without a signer, and cannot be built without a node to check the chain id against — SC-11) | dispatch answers `409` `no_chain_gateway` and **persists nothing**; reads unaffected |
| Rigorix `rigorix-server` started with `RIGORIX_SANDBOX` **and** `RIGORIX_HMAC_KEY` | dispatch (the governed broadcast) | dispatch answers `409` with the host's own reason; the order keeps its hash and stays `signed` |
| Deployed `PaymentRouter.sol` + funded signer | a payment that actually mines | the order reaches `submitted` and its tx reverts on chain if the router is not deployed at the configured address; `/v1/anchors` answers `501`. No Anvil/Sepolia deployment exists in this environment |

Boot order inside the app (see `src/apps/shell.py`): engine → session factory → **Alembic upgrade to
head** → each context's startup hook. Settlement's hook builds the six read services against the session
factory, then composes `DispatchPayment` with its two real adapters (`AuthorityHttpAdapter`,
`RigorixCommandAdapter`) and stores everything on `app.state.settlement_services`. The chain slice will
publish its gateway as `app.state.settlement_chain_gateway`; the hook passes it through when it exists.

### Health

| Endpoint | Meaning |
|---|---|
| `GET /healthz` | process is alive |
| `GET /readyz` | DB reachable (`checks.database == "ok"`) **and** `build.pending_contexts` lists contexts not yet wired — Settlement being listed there is truthful, not a bug |

### Configuration (Settlement-relevant)

| Setting | Default | Used for |
|---|---|---|
| `BURSAR_CONSOLE_DATABASE_URL` | `sqlite+aiosqlite:///./data/bursar.db` | orders/receipts/nullifiers/outbox |
| `BURSAR_CHAIN` | `anvil` | which network an order is bound to (**future dispatch**) |
| `BURSAR_CHAIN_ID` | `31337` | cross-checks `ChainNetwork.for_chain` |
| `BURSAR_PAYMENT_ROUTER_ADDRESS` | zero address | **must** be set before dispatch can work |
| `BURSAR_USDC_ADDRESS` | zero address | **must** be set before dispatch can work |
| `BURSAR_CONFIRMATIONS_REQUIRED` | `1` | finality threshold (`ChainNetwork.confirmations_required`) |
| `BURSAR_SETTLEMENT_PRIVATE_KEY` | empty | signer for the router call (**operator-held; never in an agent workspace**) |
| `BURSAR_RIGORIX_BASE_URL` | `http://127.0.0.1:8080` | the JSON-RPC host; the client posts to `{BASE_URL}/rpc` |
| `BURSAR_RIGORIX_RUN_TEMPLATE` | `bursar-payment-dispatch` | **operational knob:** the one template whose single `run_command` step is the dispatch command. It is overwritten per dispatch with the order's generated command (SC-2), so never pre-seed it with a different step |
| `BURSAR_RIGORIX_SANDBOX` | empty | **operational knob:** `container` or `vm`. Empty means *no declared boundary*, and the server then refuses every `run_command` step. Must agree with how the **server** was started (see §6) |
| `BURSAR_RIGORIX_RPC_TIMEOUT_SECONDS` | `30` | timeout for one `template.create`/`run` call; a timeout is a refusal, never a success |
| `BURSAR_PRECONDITION_URL` | `http://127.0.0.1:8001/v1/precondition/check` | the Authority origin the gate reads (`GET /v1/intents/{id}/determination`, `GET /v1/intents/{id}`) |
| `BURSAR_PRECONDITION_TIMEOUT_SECONDS` | `5` | gate timeout; **fail closed** — a slow Authority refuses the dispatch |

Configuration is a `Settings` object with prefix `BURSAR_`; no address is hardcoded in the domain. The
`ChainNetwork` value object is the only place a chain id is bound to a router/USDC pair (SC-11).

---

## 3. Graceful shutdown

```bash
# SIGTERM the uvicorn process; the lifespan closes the pool.
kill -TERM "$(pgrep -f 'src.apps.console_api.app')"
```

The lifespan disposes the engine after in-flight requests finish. Settlement holds **no in-process
queue**: events are in `settlement_outbox`, so a shutdown cannot lose a fact. A half-open request is
rolled back by `session_scope`; the write-ahead hash rule means a rolled-back order has no hash and no
broadcast (SC-3).

---

## 4. Common failure modes and recovery

| Symptom | Likely cause | Recovery |
|---|---|---|
| `409 duplicate_settlement` on dispatch | the invoice's nullifier is spent locally, or an order already exists for that intent | **Do not retry.** Confirm with `GET /v1/nullifiers/{value}`; the invoice is settled or in flight. A retry is the double-pay the lock exists to stop |
| `409 second_transaction_refused` | a second tx hash was offered for an order that has one | Keep the original hash and re-poll. Never sign again (SC-3) |
| `409 order_already_concluded` | conclusion replayed | Read `GET /v1/orders/{id}`; terminal states are `confirmed`/`reverted`/`abandoned` |
| `409 settlement_not_final` | receipt below `confirmations_required` | Wait; the order stays `PENDING` and **no cap is committed** (SC-7) |
| `409 amount_integrity_violation` | submitted amount ≠ signed intent amount | Refuse; inspect the intent and the order's `amount_usdc`. This is a bug, not a retry |
| `422 receipt_cost_missing` | a chain adapter produced a receipt without gas/fee | Fix the adapter. Do not insert a zero — `CostSummary` would under-report (SC-10) |
| `422 unknown_network` | chain id has no `ChainNetwork` | Add the configuration deliberately; there is no default on purpose (SC-11) |
| `409` on dispatch, message contains `no execution boundary declared` | the Rigorix server was started **without** a declared sandbox, so it refused the `run_command` step | Restart the server with the boundary declared (§6), set `BURSAR_RIGORIX_SANDBOX` to the same value. The order is `signed` with its hash and bytes persisted and was **not** broadcast: follow §6 "Operating a `signed` order" — do not dispatch again |
| `409` on dispatch, message contains `no chain gateway` | this process could not build the signing gateway (no settlement key, or no reachable node — SC-11 needs the chain id) | Fix `BURSAR_SETTLEMENT_PRIVATE_KEY` / `BURSAR_RPC_URL` and restart. Nothing was persisted, so the intent can still be dispatched |
| `409` on dispatch, message contains `owner's signature` | the intent requires the owner's EIP-712 signature and the settlement key cannot produce it (A-15) | Refuse, permanently: this payment needs the owner. Nothing was signed or persisted |
| `409` on dispatch, message contains `nodata`/`already known` from `payments.broadcast` | the bytes reached the node earlier (the governed step ran, the response was lost) | Read `GET /v1/orders/{id}/receipt`. If a receipt exists the payment is on chain; never re-send and never re-sign |
| `409` on dispatch, message contains `determination` or `HTTP 5xx` | Authority could not be read; the gate fails closed (SC-1) | Bring Authority back. A verdict read earlier is not a permission; the refused intent needs a fresh dispatch |
| `409` on dispatch, message contains `timed out` | Authority or Rigorix did not answer inside the configured timeout | Check the host and the two timeout knobs; a timeout is a refusal, not a maybe |
| `501` on `/v1/intents/{id}/dispatch` | the process did not compose the dispatch service (no `Settings` at startup) | Boot through the composition root (`src.apps.console_api.app`), not a bare router |
| `501` on `/v1/anchors` | no `ChainGateway` adapter | Deploy the adapter + `PaymentRouter.sol`; see §6 |
| `501` on `/v1/anchors` | the `ChainGateway` adapter exists but is not installed in the composition root | Deploy `PaymentRouter.sol` for the target chain and pass `Web3ChainGateway` to `AnchorHashService`; see §6 |
| `409 order_already_concluded` on a re-dispatch of a `signed` order | SC-4: the intent already has an order, so there is no second dispatch slot | This is correct. Recover the existing order's bytes instead (§6) — a re-dispatch would be a second payment |
| `404` on `/v1/orders/{id}/receipt` | order exists, no receipt yet | Expected while the order is `ORDERED`/`SUBMITTED` with no mined receipt |

### Recovering a stuck order

1. `GET /v1/orders/{id}` → read `tx_hash` and `status`.
2. If `tx_hash` is set, **re-poll the same hash**. Never re-sign (SC-3). `signed` means "signature made,
   nothing broadcast" — the recovery for that state is §6's procedure.
3. If the receipt is `reverted`, the order is terminal: release the reservation upstream, keep the
   hash, record the reason.
4. If the order has no hash, nothing was broadcast; it may be abandoned, not retried with a new nonce.

---

## 5. Observability

| Signal | Where |
|---|---|
| Structured JSON logs | `src/shared/infrastructure/logging.py`; `request.*`, `service.started/stopped`, `db.engine.created` |
| Correlation id | middleware in `src/shared/infrastructure/middleware.py`; propagated to events via `correlation_id` = intent id (ADR-003) |
| Metrics | `src/shared/infrastructure/metrics.py` (framework present; Settlement adds no custom counters yet) |
| Business facts | `settlement_outbox` rows (`SettlementOrdered`, `SettlementSubmitted`, `SettlementConfirmed`, `SettlementReverted`, `NullifierSpent`, `DuplicateSettlementBlocked`, `ReceiptAnchored`) |
| Cost | `GET /v1/receipts?day=YYYY-MM-DD` → `cost` (derived from receipt rows only, ADR-006) |
| Domain refusals | ADR-004 envelope with a stable `reason_code` and HTTP 409/422 |

**Alerts worth having (when dispatch lands):** any `SettlementReverted` (a refusal is a fact, but a
spike is a signal); an order `SUBMITTED`/`PENDING` beyond the network's finality window; any
`second_transaction_refused` (means a retry path exists where none should).

---

## 6. Integration gaps (must be closed before real money moves)

These are recorded deliberately. A `B-n` entry is a **contract-level** blocker: an agent must not amend a
frozen contract to close one (ADR-009), and a human unfreezes, reviews and re-freezes. A `G-n` entry is an
operational gap — code that exists or a deployment that does not.

| Id | Gap | What is needed |
|---|---|---|
| **B-1** | ✅ **Closed** — `ChainGateway.submit(order) -> str` broadcast *and* returned the hash, so SC-3's "persist the hash before broadcast" could not be expressed | The two-phase port (`prepare(order) -> SignedPayment`, then `broadcast(signed)`), `SettlementOrder.mark_signed` + `SettlementStatus.SIGNED`, and the governed `payments.broadcast` step. Recorded in `docs/contracts/settlement-contract-freeze.md` §7 |
| **B-2** | `SettlementStatus.PENDING` / `ABANDONED` exist and the state diagram transitions into them, but `SettlementOrder` has no intention method — so `SettleOnce` cannot conclude an order | Add `mark_pending(confirmations, required)` and `abandon(reason)` to the aggregate (unfreeze → review → re-freeze). Until then an order stops at `submitted` |
| **G-1** | Chain adapter built, **no deployment** | `BURSAR_PAYMENT_ROUTER_ADDRESS`, `BURSAR_USDC_ADDRESS`, `BURSAR_SETTLEMENT_PRIVATE_KEY` for the intended chain (SC-11) |
| **G-2** | `PaymentRouter.sol` built (solc 0.8.24, `evm_version = paris`), **not deployed** | `forge create` (or the deployment script) on a machine with foundry; the address lands in `BURSAR_PAYMENT_ROUTER_ADDRESS` |
| **G-3** | ✅ **Closed** — no Rigorix executor | `RigorixCommandAdapter` implements `PaymentExecutor`: one module-constant command (SC-2) rendered from `order.command_params()`, a per-order `run_command` template, `execution_id = order.id`, and the step's error surfaced verbatim on a refusal |
| **G-4** | ✅ **Closed** — no Authority HTTP surface | `AuthorityHttpAdapter` implements `DeterminationGate` as a **live** read (SC-1); it fails closed on timeout, non-200, a malformed body or an answer for another intent |

Residual on G-4: the gate reads `GET /v1/intents/{id}/determination`, which Authority exposes to the
owner's `authority:read` scope, so the settlement worker presents the demo owner token in single-household
deployments. A real deployment issues a dedicated read-scoped token (ADR-005). An `escalate` verdict does
not carry the approval bit on that response, so the gate treats it as **not permitted** until an
approval-scoped read exists — fail closed, never an implicit allow.

G-1 and G-2 are closed **in code**, not in the deployment: the contract compiles and behaves (its 11
capabilities are asserted against a real EVM), and the adapter drives it end to end on `eth-tester`, but
neither has touched Anvil or Base Sepolia. The gap that remains is operational — a deployment and a funded
key — and it is the honest one to keep on the list until a transaction has been mined on the target chain.

`SettleOnce` stays unimplemented and `/v1/anchors` stays `501` on an undeployed router. That is the
intended state: a green demo that cannot move USDC is worse than a loud gap.

### Running the governed broadcaster

The write path is split on purpose: **signing is in-process** (that is where the tx hash comes from, so the
order can hold it before anything is sent — SC-3), and **broadcasting is a Rigorix `run_command` step**
(`payments.broadcast --raw-tx <hex>`), so the payment action keeps its HMAC-signed audit envelope.

```bash
# The console script the governed step runs. It sends ONE already-signed transaction:
#   - no database, no order lookup, no network re-derivation, no signer.
# It writes the tx hash to stdout on success, and the node's own reason to stderr (exit 1) on refusal.
payments.broadcast --raw-tx 0x02f8...
```

If `payments.broadcast` is not on `PATH` inside the Rigorix sandbox, the step fails with a shell error and
the order stays `signed` — the bytes are still here, so nothing is lost, but the host image needs the
package installed (`pip install .` in the console-api image).

### Running Rigorix with a declared sandbox boundary

`run_command` refuses to spawn anything unless the server declares its execution boundary. The value is a
property of the **server process**, and Settlement's `BURSAR_RIGORIX_SANDBOX` records it; both must agree,
or every dispatch is refused (which is the honest outcome — a filter is not isolation):

```bash
# workspace root; the verified local host serves JSON-RPC on :3001
RIGORIX_SANDBOX=container RIGORIX_HMAC_KEY=<key> rigorix-server

# and the console/API side
BURSAR_RIGORIX_BASE_URL=http://127.0.0.1:3001 \
BURSAR_RIGORIX_SANDBOX=container \
BURSAR_RIGORIX_RUN_TEMPLATE=bursar-payment-dispatch \
  make run-console
```

`RIGORIX_HMAC_KEY` is what makes the audit envelope signed: without it the run's evidence is not
verifiable, and the payment action loses the guarantee it exists for. The server's value must be the same
operator-held secret this deployment signs envelopes with (`BURSAR_HMAC_KEY`) — two different keys verify
nothing.

Without `RIGORIX_SANDBOX` the server answers the run with a `Failed` step whose `error` says no boundary
was declared; the adapter raises that text verbatim as a `409`, so an operator reads the host's own reason
and nothing is reported as broadcast. The order keeps its hash and stays `signed`.

### Operating a `signed` order (signed, not broadcast)

`signed` means: the payment was signed in-process, the tx hash **and** the signed bytes are persisted,
and no node has been handed them. It is a normal state with one recovery, and it is never fixed by
dispatching again — the intent already has an order, so a second dispatch answers
`409 duplicate_settlement` (SC-4).

1. `GET /v1/orders/{id}` → `status: "signed"` and a `tx_hash`.
2. Check whether the bytes actually reached the chain anyway (the governed step may have succeeded while
   the response was lost): `GET /v1/orders/{id}/receipt`. A receipt means the payment is on chain — do not
   re-send.
3. No receipt? Re-send **the same bytes**, by hand:

   ```bash
   # the persisted write-ahead record (SC-3), read from the order row
   sqlite3 data/bursar.db \
     "select tx_hash, raw_transaction from settlement_orders where id = '<order id>';"

   # the same command the governed step runs — one already-signed transaction, no signing, no lookup
   BURSAR_RPC_URL=<the chain's RPC> payments.broadcast --raw-tx <raw_transaction>
   ```

   Same bytes, same nonce, one transaction; the on-chain nullifier refuses a genuine second payment
   (SC-5). The cost, stated plainly: run by hand it does **not** produce a Rigorix audit envelope, which
   is why it is an operator action and not an API. No endpoint or CLI re-hydrates an order for you — that
   would be a second payment path, and the persisted `raw_transaction` column is the record instead.
4. Never sign again: a new signature is a new nonce, which is the double-pay the whole ordering exists to
   prevent. If the bytes are gone, the order is `ABANDONED` material (B-2), not a re-dispatch.


---

## 7. Operational checklist (demo day)

- [ ] `make db-upgrade` ran; `settlement_orders`, `settlement_nullifiers`, `settlement_receipts`,
      `settlement_outbox` exist
- [ ] `GET /readyz` → `database: ok`
- [ ] `scripts` prove the contract: `bash .pi/scripts/ci/check_settlement_contracts.sh`
- [ ] Chain suite is green without foundry: `pytest tests/unit/settlement/chain -q` (compiles with
      `py-solc-x` 0.8.24, executes on `eth-tester`; the first run downloads the compiler once)
- [ ] `bash .pi/scripts/freeze.sh verify --module settlement` (or `status` shows `implemented`)
- [ ] If dispatch is enabled: `BURSAR_PAYMENT_ROUTER_ADDRESS`, `BURSAR_USDC_ADDRESS`,
      `BURSAR_SETTLEMENT_PRIVATE_KEY` set for the **intended** chain, and `BURSAR_CHAIN_ID` matches it
- [ ] Rigorix is up at `BURSAR_RIGORIX_BASE_URL` and was started with **both**
      `RIGORIX_SANDBOX=container` and `RIGORIX_HMAC_KEY=<the operator-held key>`; `BURSAR_RIGORIX_SANDBOX=container`
      in the API environment and `BURSAR_RIGORIX_RUN_TEMPLATE` is the template name you expect (default
      `bursar-payment-dispatch`)
- [ ] `payments.broadcast` is on `PATH` **inside the Rigorix sandbox** (`pip install .`), and
      `BURSAR_RPC_URL` there points at the intended chain
- [ ] `make db-upgrade` reached revision `005_settlement_signed` — a `signed` order without that column
      cannot be recovered
- [ ] Authority is up at the `BURSAR_PRECONDITION_URL` origin — a missed gate fails **closed**, so a
      dispatch will refuse rather than run
- [ ] Nullifier check works: `GET /v1/nullifiers/{value}` returns the spending order for a known one
