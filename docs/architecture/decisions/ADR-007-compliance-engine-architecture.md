# ADR-007: Constitution Enforcement Engine Architecture

**Status:** Accepted
**Date:** 2026-11-13

## Context

The blueprint's ADR-007 slot is "Compliance Engine Architecture". Here that is not a
regulatory module — it is **the enforcement engine**, the thing that makes the pitch true:

> *The agent proposes; the code disposes.*

Nothing in the system is more consequential than the question *"may this payment move?"*
and the answer must hold even when the agent is compromised or the operator key is stolen.
The layer stack is fixed by the business context:

1. **Rigorix OSS `rigorix-server`** (unmodified, Rust) with the Python SDK: `execute`,
   `approve`, `audit.read`.
2. **Config**: `.rigorix/preconditions.toml`, `.rigorix/sequence-policy.toml`,
   `.rigorix/capacity.toml`; approval binding; signed envelopes.
3. **Rigorix `run_command`**: a payment step with a **fixed `command` path** plus structured
   params (`intent_id`, `invoice_id`, `payee`, `payee_address`, `amount_usdc`, `bank_digest`,
   `is_new_payee`, `requires_owner_signature`), generated **by code, never by the LLM**.
4. **Authority service**: separate FastAPI + SQLite process; the precondition program is a
   thin HTTP client outside the agent-writable workspace, invoked by Rigorix at dispatch.
5. **`PaymentRouter.sol`** (Foundry, USDC on Base Sepolia, Anvil fallback): commit-point lock.

Crucially: **Rigorix does not know what "payee eligible" means.** It enforces the operator's
determination. The domain judgment lives in Authority; the atomicity and the final stop live
on-chain.

## Decision

Implement enforcement as **three concentric locks**, each of which independently refuses a
bad payment, with no LLM present in any of them.

**Lock 1 — Rigorix config (declarative, pre-dispatch).**
- `preconditions.toml` binds the dispatch to a *called* precondition program (the Authority
  HTTP client). If the precondition program is unreachable, the dispatch **fails closed**.
- `sequence-policy.toml` enforces order: an intent must be `determined → (signed) → dispatched`.
  A dispatch of an undetermined intent is a policy violation, not a runtime error.
- `capacity.toml` mirrors the daily cap as a *defence in depth* count, so even if Authority
  is bypassed Rigorix refuses past the ceiling. Authority remains the source of truth; this is
  a belt, and the two disagreeing is itself an alert.
- Envelopes are signed (HMAC) for `audit.read` cross-checks.

**Lock 2 — Authority service (the domain judgment).**
- Invoked at dispatch time as a precondition. Re-reads constitution version and payee
  eligibility **in that request** — never from a cached plan-time value.
- Performs the atomic reservation (`committed + reserved + amount <= cap`) and returns
  `allow | deny | escalate` with reason codes.
- Enforces signature binding for `is_new_payee` or `amount > threshold`.
- **Stateless with respect to the agent**: it accepts structured params and never executes
  anything the agent supplied except the invoice/attempt identifiers.
- A denial returns non-zero and no command runs. A refusal has **no side effect** but is
  still enveloped.

**Lock 3 — `PaymentRouter.sol` (commit point).**
- Re-checks: nullifier unspent (`invoiceHash`), owner signature valid over the EIP-712 typed
  data, payee address equals the signed address, amount equals the signed amount, allowance
  and per-tx cap respected.
- A revert is terminal for that attempt. Retrying a reverted nullifier is a **refusal**, never
  a retry loop (prevents the timeout double-pay).
- Also stores the anchor for evidence hashes (`anchor(bytes32 hash)`).

**Explicit ordering rule:** authority is re-read at the moment of consequence, so a payee
frozen between approval and dispatch is refused at Lock 2 even though Lock 3 would have
accepted the signature. Scenario 3 exists to prove exactly this.

**Latency rule:** all three locks are local (no external oracle, no LLM call). Total added
latency is one HTTP call plus one contract call — inside NFR-001.

## Consequences

- Three independent failure modes are all refusals with evidence; a single compromised lock
  is not sufficient to move money.
- Rigorix and Authority can disagree (cap mirror), which is *desirable* but must be alertable,
  not silently reconciled.
- Fail-closed on precondition unreachability means an Authority outage stops payments. That is
  the correct trade for this domain — a stalled payment is recoverable, a wrong one is not.
- The EIP-712 struct must be generated once and consumed by both Python and Solidity; a
  divergence is the highest-severity defect class in the project.
- No LLM anywhere in Lock 1–3 makes principle 7 checkable by a test that asserts the
  enforcement package imports no model client (NFR-002).

## Alternatives Considered

| Alternative | Pros | Cons | Reason Rejected |
|---|---|---|---|
| Rules only in `.rigorix/*.toml` (no Authority service) | Fewest parts, all declarative | TOML cannot express payee eligibility, digest comparison, or atomic reservations | Rejected — the interesting rules aren't static |
| Rules only in Authority (no Rigorix) | One place to reason | No sequence policy, no signed audit trail, no operator-owned constitution artifact | Rejected — loses the governance story and the "operator cannot be talked out of it" claim |
| Rules only on-chain | Maximum finality | Every rule change costs a deploy; no evidence story; no readable refusals | Rejected — no UX, no audit |
| LLM-as-judge for edge cases | Flexible | Non-deterministic, prompt-injectable, unauditable | Rejected — violates principle 7 explicitly |
| Rigorix fork with payee logic inside | Single source | Hours lost, OSS claim broken, unauditable diff | Rejected — hard constraint: use unmodified |

## Affected Modules

- Authority (precondition program = its `interfaces/` entrypoint)
- Settlement (`run_command` generation, tx submission, nullifier reconciliation)
- Evidence (envelope signing, anchoring through the router)
- Mandate (the constitution the engine reads)

## Related ADRs

- ADR-001 (why Authority is a separate process), ADR-002 (reservation atomicity),
  ADR-005 (the signature layer), ADR-006 (budget guard precondition)