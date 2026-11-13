# ADR-005: Authentication & Authorization (API Keys + Scopes, EIP-712 for Consequence)

**Status:** Accepted
**Date:** 2026-11-13

## Context

There are four principal types, and they are **not** interchangeable:

| Principal | Capability |
|---|---|
| Owner (human, phone) | Change rules, register payees, freeze, re-approve digests, sign escalated payments |
| Payer (human) | Read-only view of their own bills |
| Agent (software) | Propose payments. Nothing else. |
| Operator / Rigorix | Dispatch preconditions. Cannot widen authority. |

An API key alone cannot express "the owner approved *this* payment" — a key is a bearer
token that a prompt injection could reuse. The business context is explicit: *approval binds
to the exact payment, not to a screen*, and *authority is re-read at the moment of consequence*.

## Decision

Two-layer authorization:

**Layer 1 — request authentication (API key + scope).**
- Opaque API keys, `Authorization: Bearer <key>`, stored hashed (SHA-256) with a scope set.
- Scopes are coarse and context-scoped: `mandate:read`, `mandate:write`,
  `billing:propose`, `billing:read`, `authority:evaluate`, `authority:sign`,
  `authority:read`, `settlement:read`, `evidence:read`, `console:read`.
- The **agent key** may hold only `billing:propose`, `billing:read`, `authority:evaluate`.
  It provably cannot hold `mandate:write` or `authority:sign` — an authorization test matrix
  asserts this (NFR-016).
- The agent key is never mounted into the authority service's environment.

**Layer 2 — consequence authorization (owner signature).**
- For anything that moves money against the owner's intent (new payee, above threshold,
  bank-digest re-approval), possession of a key is **not** sufficient. The owner must
  produce an **EIP-712 signature over the exact intent fields** (`intent_id`, `invoice_id`,
  `payee`, `payee_address`, `amount_usdc`, `bank_digest`, `is_new_payee`,
  `requires_owner_signature`, `nonce`, `expiry`).
- Authority verifies off-chain by recovering the signer and comparing to the mandate owner;
  `PaymentRouter` verifies the same typed data on-chain. Off-chain and on-chain must agree —
  a divergence is a critical bug, not a fallback.
- Approvals are **single-use, expiring, and bound**: changing any field invalidates them.

Additional rules:
- Payer tokens are read-only and scoped to one household; the payer has no key material.
- No secrets in the agent workspace: the HMAC key, API keys and the settlement wallet key
  live in the operator environment only.
- Every 401/403 is itself an auditable event (`EvidenceVerificationFailed` is not the vehicle;
  a dedicated `AccessDenied` envelope is).

## Consequences

- A stolen operator key can still *ask*; it cannot *authorize* a payment outside the
  constitution, and it cannot exceed the caps because the ledger check is not key-gated.
- The owner must be present to sign escalations — that is the product, not a limitation.
- Two verification implementations of the same typed data (Python + Solidity) must be kept in
  lockstep; a shared spec file generates both (see EnterWork risk R-2).
- The demo needs a wallet on the owner's phone/browser; a local Anvil key is the fallback.

## Alternatives Considered

| Alternative | Pros | Cons | Reason Rejected |
|---|---|---|---|
| Single owner API key for everything | Trivial | Stolen key = drained account; agent key escalation | Rejected — kills the second lock |
| JWT with roles | Standard | Still bearer; no per-payment binding | Rejected — the binding is the point |
| Session cookies + CSRF | Browser-friendly | Doesn't fit agent-to-service, no binding | Rejected |
| OAuth2 client credentials | Proper for agents | Server, flows, tokens — hours; still no payment binding | Rejected — over-scope, solves the wrong problem |
| On-chain-only authorization (no API scopes) | Fewest moving parts | Off-chain preconditions need identity; refusals need an actor | Rejected — cannot attribute refusals |

## Affected Modules

- Mandate, Authority, Console (all endpoints in their API tables carry an Auth column).

## Related ADRs

- ADR-004 (endpoints and error envelope), ADR-007 (the on-chain half of the signature check)