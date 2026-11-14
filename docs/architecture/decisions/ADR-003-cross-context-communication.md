# ADR-003: Cross-Context Communication via Domain Events

**Status:** Accepted
**Date:** 2026-11-13

## Context

The context map has ten edges. Some are calls (Console reads Authority), some are
conformist reads (Authority reads Mandate), and several are **reactions**: a determination
must be sealed as evidence, a settlement receipt must commit or release a reservation, a
refusal must still be recorded.

If reactions are implemented as direct calls, two things break:

1. **Refusals get skipped.** The refusal path is the exceptional path; a direct call inside
   an `except` block is exactly what a rushed implementation drops (violates principle 5,
   "every attempt leaves evidence, including refusals").
2. **Evidence becomes a hard dependency of Authority.** Evidence is a supporting context;
   if its failure can abort a determination, a witness has veto power over the guard.

## Decision

Use **in-process asynchronous domain events with a transactional outbox**.

- Every state change that a domain expert would care about publishes a **domain event**
  (see each tactical module's Domain Events table).
- Publishes go to `<context>_outbox` **in the same transaction** as the state change; a
  background dispatcher drains the outbox and delivers to subscribers.
- Delivery is **at-least-once**; every subscriber handler is keyed by `(event_id, handler)`
  so redelivery is a no-op. Events carry `event_id`, `occurred_at`, `aggregate_id`,
  `correlation_id` (the payment intent id where one exists).
- **Refusals are events too.** `PaymentRefused`, `ProposalRejected`, `ApprovalRejected`,
  `CapacityRefused`, `SettlementReverted` are first-class and are sealed as evidence.
- Events are **facts in the past tense**; a command is never an event. A subscriber must not
  be able to reject a fact — if it cannot process an event it retries and then quarantines it
  for inspection, never rolls back the publisher.
- Cross-context **queries** (Console reading Authority) are not events: they go through
  explicit read-model ports.

Delivery table:

| Event | Publisher | Subscribers |
|---|---|---|
| `PaymentAllowed`, `PaymentRefused`, `ApprovalGranted` | Authority | Settlement (dispatch gate), Evidence, Billing (attempt status) |
| `SettlementConfirmed`, `SettlementReverted` | Settlement | Authority (commit/release), Billing (invoice settled), Evidence |
| `InvoiceRecorded`, `PaymentProposed` | Billing | Authority (triggers evaluation), Evidence |
| `PayeeQuarantined`, `PayeeFrozen`, `ConstitutionVersionPublished` | Mandate | Authority (invalidates plan-time view), Evidence |
| `EnvelopeSealed` | Evidence | Console (read model) |

## Consequences

- The refusal path is symmetric with the success path, so scenario 2/3 assertions
  ("no transaction, but a verifiable envelope") become natural rather than special-cased.
- Eventual consistency between "determination issued" and "evidence sealed". The console
  must render a pending-evidence state; the demo asserts within a bounded wait.
- One extra table per publishing context and one dispatcher loop; no broker, no Celery.
- Poison events are quarantined, never dropped, and quarantine itself is enveloped.

## Alternatives Considered

| Alternative | Pros | Cons | Reason Rejected |
|---|---|---|---|
| Direct synchronous calls | Simple, immediate | Refusal path drops evidence; Evidence gains veto power | Rejected — breaks principle 5 |
| External broker (Redis/RabbitMQ/Kafka) | Real durability, fan-out | Another service to run in 24h; demo fragility | Rejected — over-scope |
| Rigorix `audit.read` as the only event log | Already built, signed | Rigorix does not know domain semantics; not queryable per aggregate | Rejected as sole mechanism; used as a cross-check |
| Synchronous in-process callbacks (no outbox) | Easy | Events lost if the process dies mid-call; no replay for the demo | Rejected — evidence must survive |

## Affected Modules

- All six module docs (Domain Events sections).

## Related ADRs

- ADR-002 (outbox shares the transaction)
- ADR-004 (read models exposed over REST)