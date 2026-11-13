# ADR-004: API Design (REST + JSON, OpenAPI-first, /v1)

**Status:** Accepted
**Date:** 2026-11-13

## Context

The frontend is a **separate React/TypeScript/Vite app** built in parallel by a different
pair of hands against mocks (NFR-006). The backend therefore cannot be "discovered" by
reading code — the contract has to exist before the implementation does.

At the same time, the APIs here are not uniform CRUD: the interesting endpoints are
**decisions** (`POST /v1/attempts/{id}/evaluate`), **signatures**
(`POST /v1/approvals/{id}/signature`) and **proofs** (`GET /v1/evidence/{id}/verify`).
REST purism would push these into RPC-shaped lies.

## Decision

Use **REST + JSON with an OpenAPI 3.1 contract published by hour 6**, served at `/v1`.

Conventions:

- Resources are plural nouns; the verbs that are genuinely business operations are explicit
  sub-resources (`/evaluate`, `/signature`, `/verify`) rather than a generic `/rpc` endpoint.
- **Idempotency:** every mutating endpoint accepts `Idempotency-Key`. A replay returns the
  original response, never a second side effect. This is what makes the demo's
  "double-click the approve button" moment safe.
- **Error envelope** (uniform across contexts):
  ```json
  { "error": { "code": "PAYEE_QUARANTINED", "message": "…",
               "intent_id": "0x…", "evidence_id": "…", "retryable": false } }
  ```
  A refusal is `409` with a domain `code`; it is a **normal documented outcome**, not a 500.
- **Determinations are readable**: `GET /v1/intents/{id}/determination` returns the verdict,
  reason codes, constitution version consulted and the timestamp of the re-read. The console
  shows why, not just that.
- **Versioning:** path prefix `/v1`. Breaking change = `/v2`, no in-place mutation.
- **Pagination:** cursor-based (`?cursor=&limit=`), never offset.
- The OpenAPI document is generated from FastAPI and committed; a CI check fails if the
  committed schema drifts from the app.

Two deployables, two base URLs: `authority-service` (`:8001`, enforcement-critical, no CORS),
`console-api` (`:8000`, serves the read models and proxies nothing critical).

## Consequences

- The frontend is unblocked at hour 6 and never needs to read Python.
- Refusals must be designed as documented responses, which forces the team to enumerate
  reason codes early — that enumeration *is* the domain model of refusal.
- Loosely-RESTful endpoints (`/evaluate`, `/signature`) are a deliberate compromise;
  they are named for domain operations in the ubiquitous language, not for HTTP verbs.
- Committing a generated OpenAPI file adds a drift check to CI, which costs minutes and
  catches the most expensive integration failure.

## Alternatives Considered

| Alternative | Pros | Cons | Reason Rejected |
|---|---|---|---|
| GraphQL | One endpoint, frontend-driven | Schema work, N+1 risk, no domain-shaped decisions | Rejected — extra tooling for 24h |
| Pure RPC (`POST /rpc {method, params}`) | Trivial to add endpoints | No discoverable resources; console can't cache or link | Rejected — poor for read models |
| gRPC | Typed, fast | Browser needs a proxy; React team blocked | Rejected — frontend constraint |
| No published contract (code-first discovery) | Zero overhead now | Frontend stalls at integration hour 18 | Rejected — NFR-006 explicitly forbids |

## Affected Modules

- Console (read models), Authority (decisions, approvals), Mandate (constitution, payees),
  Billing (invoices, attempts), Settlement (receipts), Evidence (envelopes, verification).

## Related ADRs

- ADR-005 (auth on every endpoint), ADR-003 (read models fed by events)