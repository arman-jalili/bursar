# Settlement — Runbook

**Module:** Settlement (Lock 3 — the commit-point lock)
**Canonical:** [`.pi/architecture/modules/settlement.md`](../.pi/architecture/modules/settlement.md)
**Contract:** [`docs/contracts/settlement-contract-freeze.md`](contracts/settlement-contract-freeze.md)
**Runtime decision:** [ADR-009](../.pi/architecture/decisions/ADR-009-runtime-wiring-multilang-judgment.md)
**Last updated:** 2026-11-14

---

## 1. What runs today

| Surface | State | Where |
|---|---|---|
| Domain (aggregate, value objects, domain services) | **Implemented** — the 80 frozen contract suites plus the 25 chain tests are green (`pytest tests/unit/settlement`) | `src/settlement/domain/` |
| Persistence (orders, nullifiers, receipts, outbox) | **Implemented** — migration `003_settlement`, 7 SQLite integration tests | `src/settlement/infrastructure/` |
| Read API (`GET /v1/orders`, `/v1/orders/{id}`, `/v1/orders/{id}/receipt`, `/v1/receipts?day=`, `/v1/nullifiers/{value}`) | **Live** in `console-api` | `src/settlement/interfaces/http/router.py` |
| `DispatchPayment` / `SettleOnce` | **Not wired** — blocked on re-freeze (B-1, B-2) | `src/settlement/application/services.py` |
| `PaymentRouter.sol` | **Built, not deployed** — solc 0.8.24, nullifier map, EIP-712 owner check, `Anchored` event; 11 pytest tests on an in-process EVM (no `forge`/`anvil` here) | `contracts/src/PaymentRouter.sol` |
| `Web3ChainGateway` (chain adapter) | **Built, not wired** — submit/receipt/nullifier reads, EIP-1559 signing, refusals instead of traces; 14 tests end to end against `eth-tester` | `src/settlement/infrastructure/chain/` |
| Rigorix `run_command` adapter | **Not built** — no Rigorix SDK dependency | — |

Two write endpoints exist in the frozen contract and answer `501` with the blocker named:
`POST /v1/intents/{intent_id}/dispatch`, `POST /v1/anchors`.

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
| Deployed `PaymentRouter.sol` + funded signer | dispatch/anchoring (not wired) | write endpoints answer `501`, reads unaffected; the contract and adapter are built but no Anvil/Sepolia deployment or funded key exists in this environment |
| Rigorix `run_command` | dispatch (not wired) | same |
| Authority determination read | dispatch (not wired) | same |

Boot order inside the app (see `src/apps/shell.py`): engine → session factory → **Alembic upgrade to
head** → each context's startup hook. Settlement's hook builds the six read services against the
session factory and stores them on `app.state.settlement_services`.

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
| `409 duplicate_settlement` on dispatch (future) | nullifier already spent locally or on-chain | **Do not retry.** Confirm with `GET /v1/nullifiers/{value}`; the invoice is settled or in flight. Escalate to the owner; a retry is the double-pay the lock exists to stop |
| `409 second_transaction_refused` | a second tx hash was offered for an order that has one | Keep the original hash and re-poll. Never sign again (SC-3) |
| `409 order_already_concluded` | conclusion replayed | Read `GET /v1/orders/{id}`; terminal states are `confirmed`/`reverted`/`abandoned` |
| `409 settlement_not_final` | receipt below `confirmations_required` | Wait; the order stays `PENDING` and **no cap is committed** (SC-7) |
| `409 amount_integrity_violation` | submitted amount ≠ signed intent amount | Refuse; inspect the intent and the order's `amount_usdc`. This is a bug, not a retry |
| `422 receipt_cost_missing` | a chain adapter produced a receipt without gas/fee | Fix the adapter. Do not insert a zero — `CostSummary` would under-report (SC-10) |
| `422 unknown_network` | chain id has no `ChainNetwork` | Add the configuration deliberately; there is no default on purpose (SC-11) |
| `501` on `/v1/intents/{id}/dispatch` | contract blocker B-1/B-2 | Requires a re-freeze (see §6); no operational workaround |
| `501` on `/v1/anchors` | the `ChainGateway` adapter exists but is not installed in the composition root | Deploy `PaymentRouter.sol` for the target chain and pass `Web3ChainGateway` to `AnchorHashService`; see §6 |
| `404` on `/v1/orders/{id}/receipt` | order exists, no receipt yet | Expected while the order is `ORDERED`/`SUBMITTED` with no mined receipt |

### Recovering a stuck order (future dispatch)

1. `GET /v1/orders/{id}` → read `tx_hash` and `status`.
2. If `tx_hash` is set, **re-poll the same hash**. Never re-sign (SC-3).
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

These are recorded deliberately. Each is a **contract-level** blocker, not a missing line of code; an
agent must not amend a frozen contract to close one (ADR-009).

| Id | Gap | What is needed |
|---|---|---|
| **B-1** | `ChainGateway.submit(order) -> str` broadcasts *and* returns the hash, so SC-3's "persist the hash before broadcast" cannot be expressed | Split the port: `prepare(order) -> SignedTx` (hash known, not sent) then `send(signed) -> str`; `DispatchPayment` persists `mark_submitted(prepare.hash)` in the same transaction, then sends |
| **B-2** | `SettlementStatus.PENDING` / `ABANDONED` exist and the state diagram transitions into them, but `SettlementOrder` has no intention method | Add `mark_pending(confirmations, required)` and `abandon(reason)` to the aggregate (unfreeze → review → re-freeze) |
| **G-1** | ~~No chain adapter~~ — **closed**: `Web3ChainGateway` implements `ChainGateway` (submit, receipt with cost and confirmations, `spentNullifiers`, anchor) and is exercised end to end against `eth-tester`. Remaining: a deployed router address and a funded signer per network | `BURSAR_PAYMENT_ROUTER_ADDRESS`, `BURSAR_USDC_ADDRESS`, `BURSAR_SETTLEMENT_PRIVATE_KEY` for the intended chain (SC-11) |
| **G-2** | ~~`PaymentRouter.sol` does not exist~~ — **closed**: `contracts/src/PaymentRouter.sol` (solc 0.8.24, `evm_version = paris`) has the `spentNullifiers` map, the EIP-712 owner check bound to chain id + verifying contract, `anchor(bytes32)` and `Anchored`. Remaining: deploy to Anvil, then Base Sepolia | `forge create` (or the deployment script) on a machine with foundry; the address lands in `BURSAR_PAYMENT_ROUTER_ADDRESS` |
| **G-3** | No Rigorix executor | `RigorixCommandAdapter` implementing `PaymentExecutor`, calling `run_command` with `order.command_params()` only |
| **G-4** | No Authority HTTP surface | `AuthorityHttpAdapter` implementing `DeterminationGate` — must be a **live** read at dispatch time (SC-1), never a cached verdict |

Until B-1 and B-2 are re-frozen, `DispatchPayment` and `SettleOnce` stay unimplemented and the write
endpoints stay `501`. That is the intended state: a green demo that cannot move USDC is worse than a
loud gap.

G-1 and G-2 are closed **in code**, not in the deployment: the contract compiles and behaves (its 11
capabilities are asserted against a real EVM), and the adapter drives it end to end, but neither has
touched Anvil or Base Sepolia. The gap that remains is operational — a deployment and a funded key —
and it is the honest one to keep on the list until a transaction has been mined on the target chain.

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
- [ ] Nullifier check works: `GET /v1/nullifiers/{value}` returns the spending order for a known one
