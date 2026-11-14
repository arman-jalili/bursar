# Architecture Decision Record: ADR-009

<!--
Canonical Reference: .pi/architecture/decisions/ADR-009-runtime-wiring-multilang-judgment.md
Blueprint Source: Guardian Framework v1.2
-->

## Title

Runtime wiring of a bounded context: installed in the composition root, with contract blockers named rather than stubbed

## Status

- [ ] Proposed
- [x] Accepted
- [ ] Deprecated
- [ ] Superseded by ADR-XXX

## Context

Settlement reached the runtime-integration step with a green domain and a green persistence layer: 80
frozen contract suites plus 7 SQLite integration tests. The question this ADR answers is what "integrated"
means for a context whose two external adapters — the chain gateway and the Rigorix command executor —
have no dependency in this build (`web3`/`eth-account` are not installed, `contracts/src` is empty, and
there is no Rigorix SDK).

Two failure modes must be avoided:

1. **Dead code that looks alive.** A service that is only referenced by its own tests is not integrated
   (ADR-009's original concern). A `build_services()` that constructs an ABC whose `execute` raises
   `NotImplementedError` is the same failure in a different shape: it boots, it appears wired, and it
   fails only when a user calls it.
2. **A freeze amended by an agent.** The remaining write path needs changes to frozen interfaces (see
   below). Silently widening a frozen contract to make a demo work destroys the guarantee the freeze
   exists for: implementation must satisfy the contract, not redefine it.

## Decision

1. **Install the read surface in the real composition root.** `src/apps/console_api/app.py` lists
   `settlement` in `HOSTED_CONTEXTS`; `install()` registers the router and a startup hook that builds the
   six read services against the app's session factory. Concretely reachable over HTTP:
   `GET /v1/orders`, `GET /v1/orders/{id}`, `GET /v1/orders/{id}/receipt`, `GET /v1/receipts?day=`,
   `GET /v1/nullifiers/{value}`. Each is covered by an E2E test that boots the composition root.
2. **Name blocked write endpoints instead of faking them.** `POST /v1/intents/{id}/dispatch` and
   `POST /v1/anchors` exist (the frozen contract lists them) and answer `501` with a message that names
   the blocker. An endpoint that silently 500s, or that "succeeds" against a fake chain, hides the gap.
3. **Do not amend the freeze from inside an implementation item.** The blockers are recorded here and in
   `docs/runbook-settlement.md` (Integration gaps). A human unfreezes, reviews and re-freezes; only then
   do `DispatchPayment`/`SettleOnce` and the chain adapter get written.

### The two contract blockers (for the re-freeze)

| # | Blocker | Why the frozen signature cannot express it |
|---|---------|--------------------------------------------|
| B-1 | `ChainGateway.submit(order) -> str` broadcasts **and** returns the hash | SC-3 requires the hash to be persisted *before* broadcast. With this signature the caller learns the hash only after the transaction is on the wire. A sign/prepare step (or a two-phase port) is required. |
| B-2 | No `PENDING` / `ABANDONED` transition on `SettlementOrder` | `SettlementStatus` declares both and the module doc's state diagram transitions into them, but the aggregate exposes no intention method. An application service would have to assign `order.status` from outside — precisely what S-4 forbids. |

Two further findings were resolved during implementation without changing a frozen test (details in the
module doc and code comments):

- `SettlementOrder` gained `bank_digest`, `is_new_payee` and `requires_owner_signature`; `command_params`
  must return the digest and the escalation bits, and the module doc's stub already read them from the
  order.
- The nullifier seed is the invoice **identity**, not the content hash. A content hash changes when a bill
  is re-issued (a corrected PDF), which would mint a second nullifier for one invoice and defeat scenario
  6. The frozen test pins `invoice_id`; the derivation and its rationale live in `Nullifier.derive`.

## Alternatives Considered

| Alternative | Pros | Cons | Reason Rejected |
|-------------|------|------|-----------------|
| Wire fake adapters (in-memory chain, no-op executor) into the production app | Every endpoint returns 200; demo looks complete | A green demo that cannot move USDC is the failure mode ADR-006/007 exist to prevent; production would ship a fake lock | Rejected: refuses to make a safety claim the code cannot back |
| Implement `DispatchPayment`/`SettleOnce` against the current ports and "best effort" the write-ahead ordering | Full code path exists | SC-3 is violated (persist-after-broadcast); a crash between broadcast and save re-signs and pays twice | Rejected: it is exactly the timeout double-pay the contract forbids |
| Unfreeze the contract inside this item | Unblocks the above | An agent deciding its own contract changes removes the phase separation the freeze guarantees | Rejected; left to a human re-freeze |
| Register nothing and defer the whole context | No half-wired surface | Loses the read path the console and evidence can use today | Rejected |

## Consequences

### Positive

- The console and Evidence can read orders, receipts, cost and nullifier status from the real service
  today — no direct table access, no second read model.
- The remaining blockers are machine-visible (501 messages) and human-visible (this ADR, the runbook),
  not buried in a TODO.
- The freeze evidence stays intact: no frozen test and no `docs/contracts/settlement-contract-freeze.md`
  byte was changed.

### Negative

- Dispatch and anchoring are not usable until the re-freeze. The demo path cannot move USDC yet.
- The read surface has no real data until `DispatchPayment` exists or an operator seeds orders.

### Neutral

- `settlement_services` lives on `app.state`, the same shape Billing and Mandate use, so the shell does
  not grow context-specific code.

## Implementation

**Affected Modules:** Settlement, Console API (composition root)

**Files:**
- `src/settlement/application/services_impl.py` — six read services (+ `GetOrder`, `ListReceipts`,
  `NullifierStatus` behind the frozen endpoints)
- `src/settlement/interfaces/http/{router,schemas,deps,__init__}.py`
- `src/apps/console_api/app.py` — `settlement` added to `HOSTED_CONTEXTS`
- `tests/integration/settlement/test_http_api.py` — E2E through the composition root

**Verification:** `pytest tests/integration/settlement/test_http_api.py`,
`bash .pi/scripts/validate-runtime-wiring.sh`, `bash .pi/scripts/check_composition_root.sh`.

**Related ADRs:** ADR-001 (one process, one database), ADR-004 (error envelope), ADR-006 (cost from
receipts), ADR-007 (the contract is the final arbiter).
