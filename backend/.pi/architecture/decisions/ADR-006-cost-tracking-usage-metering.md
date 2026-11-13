# ADR-006: Cost Tracking & Usage Metering (Gas, Fees, Spend Attribution)

**Status:** Accepted
**Date:** 2026-11-13

## Context

Bursar is not a SaaS and has no tenants to bill, so the blueprint's "cost tracking & usage
metering for customer billing" does not apply. But **three real cost questions** do, and two
of them are domain questions, not infrastructure questions:

1. **Domain spend.** How much of the owner's money has been committed today, and does it fit
   under the cap? This already exists as Authority's `CapLedger` — but it must stay the single
   source of truth. A second "metering" ledger that disagrees with it would be a bug factory.
2. **Rail cost.** Gas per settlement, the simulated bank payout fee, and the demo-day burn
   rate on Base Sepolia. Nobody is charged, but the receipt should show what the rail cost,
   and the team needs to know when the faucet is running dry.
3. **Evidence cost.** Each `anchor` write is a transaction. Anchoring every envelope is a real
   per-event cost and a demo risk (already flagged as R-8 in the exploration).

## Decision

Treat cost as **two separate concerns with two separate owners**, and never let either
duplicate the cap ledger.

**A. Domain spend (owned by Authority, not by an infra meter):**
- `CapLedger` remains authoritative for `committed`, `reserved` and `cap` per day.
- No parallel metering table credits or debits spend. Metrics may *read* the ledger; they may
  never write to it. This is enforced by the layer rule in ADR-001 and by an architecture test.

**B. Rail cost (owned by Settlement, exposed as a read model):**
- Every `ChainReceipt` records `gas_used`, `gas_price`, `fee_usdc_estimate`, `network`,
  and whether it was a settlement or an anchor transaction.
- A `CostSummary` read model (per day, per intent) is derived from receipts — computed, never
  stored as a competing balance.
- The simulated bank payout carries an explicitly labeled `simulated_fee_usdc` and
  `payout_simulated: true`, so the console cannot accidentally present it as real.

**C. Evidence cost control (owned by Evidence):**
- Anchoring policy is explicit and configurable: `anchor_mode = per_envelope | batched | demo_only`.
- Default for the hackathon is `batched`: envelopes are sealed always, and hashes are anchored
  in batches, with the batch id recorded on each envelope. The seven demo scenarios get
  `per_envelope` anchoring so the verification story is unimpeachable (NFR-013).
- Envelope metadata states which mode produced it — batching is labeled, never hidden.

**D. Operational budget guard:**
- A `settlement_budget_usdc` config caps total gas+spend the demo will burn; when it is
  exhausted, dispatch refuses with `BUDGET_EXHAUSTED` rather than silently draining.
  This refusal is enveloped like any other.

## Consequences

- One ledger, one truth. Cost reporting is derived data, so it can never drift from the cap.
- Receipts become genuinely useful: they answer "what did this payment cost to move?"
- Batching anchors reduces chain writes but weakens per-event time proofs; the mode is
  recorded on every envelope so the trade-off is visible in the evidence itself.
- The budget guard adds a refusal path that must be tested (it is cheap and it protects the demo).

## Alternatives Considered

| Alternative | Pros | Cons | Reason Rejected |
|---|---|---|---|
| Generic metering service + usage events per call | "Proper" SaaS metering | Duplicate ledger, drift risk, hours of work, no customer to bill | Rejected — solves the wrong problem |
| No cost tracking at all | Zero work | Gas burn surprises; can't show rail cost; faucet runs out mid-demo | Rejected — demo risk |
| Anchor every envelope | Strongest per-event proof | Transaction per event; slow and costly in 24h | Rejected as default; kept for demo scenarios |
| Anchor nothing, HMAC only | Free | Loses independent integrity and time (scenario 7 fails) | Rejected — the anchor is the claim |

## Affected Modules

- Authority (`CapLedger` authority boundary, budget-guard refusal)
- Settlement (`ChainReceipt` cost fields, `CostSummary` read model)
- Evidence (anchoring modes)
- Console (cost display, labeled simulated payout)

## Related ADRs

- ADR-002 (ledger conditional update), ADR-007 (budget guard as a precondition)