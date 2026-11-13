# Bursar — 24-hour plan and analyst baseline

**Event:** Proximata Hackathon '26, track "Bringing Crypto to Everyday Life" (Crypto Club Vienna).
**Code freeze:** Saturday 14 November 2026, 15:00. **Demos:** 16:00.
**Team:** 2–4. **Repo:** public, proximata org, MIT license at root.

This plan assumes H+0 = Friday 13 Nov, 16:15 local. Adjust the clock, keep the order.

## The MVP (what must be true at 15:00)

A judge can, from one screen:

1. Send a normal invoice; the agent pays; USDC settles; the receipt appears.
2. Send a poisoned invoice ("our bank details changed"); the payment is refused with the rule
   named; no transaction is sent.
3. Open the evidence, verify the signed envelope in the browser, flip one byte, and see
   verification fail.
4. See which rule decided, in the Constitution pane.

If those four work, the submission is eligible and competitive. Everything else is upside.

## Must / Should / Stretch

### Must (do not cut)

- One household, one currency, one live settlement path.
- Rigorix on the dispatch path: plan/execute, a dispatch-time precondition, one plan-time
  sequence refusal, signed envelope.
- A `PaymentRouter` that enforces at least: operator-only, payee allowlist, invoice nullifier.
- One live payment and one live refusal.
- Browser envelope verification + flip-a-byte.
- The 3-pane UI with the agent line, the rule that decided, and the receipt.
- README, `.env.example`, MIT license, 3-minute video, written submission.

### Should (if the clock allows)

- EIP-712 owner approval for a new payee; wrong signature refused.
- Freeze-after-approval refused at dispatch (T0 → Tn).
- Daily cap catching split invoices.
- On-chain `EvidenceAnchored` hash.
- Hosted URL.

### Stretch (only after G4)

- Capacity-ledger race scene.
- Effect-commitment Ambiguous scene.
- Passkey / smart account.
- LLM agent mode.

## Tracks

| Track | Owns | First deliverable |
|---|---|---|
| **A. Governance** | console, Rigorix config, execute/approve/audit, scenarios | normal payment executes on Anvil |
| **B. Frontend** | `web/`, design system, 3 panes, approval sheet, verifier | UI shell on mocks with all five states |
| **C. Chain** | `contracts/`, PaymentRouter, deploy, Anvil/Base Sepolia | pay + duplicate revert test |
| **D. Authority** | `authority/`, determination, reservations, reconciliation | precondition pass/deny over HTTP |
| **E. Integration** | compose, hosted, video, README | one-command stack |

Team of 3: A+D, B, C+E. Team of 2: A+C, B+E; cut the approval scene.

## Hour-by-hour

| Window | Action | Gate |
|---|---|---|
| H+0–H+1 | Clean context; run `/domain --explore`; review context map; `--architect-scaffold`; freeze API/ABI/tokens; create mocks | **G0** |
| H+1–H+5 | Parallel: console skeleton + Rigorix config + authority skeleton; UI shell + tokens + panes on mocks; contract skeleton + Foundry tests; compose + README skeleton | |
| H+5–H+9 | Normal payment end-to-end on Anvil: Rigorix plan → precondition → payctl → contract → receipt → evidence | |
| H+9–H+12 | Integrate UI with the real API; poisoned invoice refusal; evidence verify + flip byte | **G2 by H+12** |
| H+12–H+15 | Sleep in shifts (4–5 h total per person); leave one person on call for the server | |
| H+15–H+17 | Approval or freeze-at-dispatch; wrong signature refused; Base Sepolia deploy | **G3** |
| H+17–H+20 | Hosted deploy; scenario buttons; polish; split cap; duplicate bypass; anchor | **G4** |
| H+20–H+22 | Record the 3-minute video; README, `.env.example`, MIT, submission text | **G5** |
| H+22–H+23 | Buffer; freeze; submit **before** 15:00 | |

## Parallel work rules

- `docs/BURSAR-BUILD-CONTRACT.md` is frozen. No track changes a type, endpoint, ABI, or token
  without a written note in that file and a message to the other tracks.
- The frontend never waits on the backend. It builds against mocks from H+0.
- The chain track never waits on the app. It tests against Anvil and publishes `config/chain.json`.
- The console never waits on the chain. It records `settlement.pending` and reconciles later.
- One person owns the demo script and the video; it is not a last-minute task.

## Cut order if behind

1. Drop the anchor tx; keep the envelope verification.
2. Drop the split-cap scene; keep the poisoned refusal.
3. Drop the freeze-after-approval scene; keep one approval.
4. Drop EIP-712 from the contract; keep the off-chain signature and the allowlist/nullifier.
5. Switch Base Sepolia to Anvil; say so on screen and in the README.
6. Never cut: the normal payment, the refusal, the evidence verify, the rule-named UI.

## Risks and pre-emptive actions

| Risk | Action now |
|---|---|
| Rust server build time | Start a release build (or pull a prebuilt image) at H+0; do not discover this at H+20 |
| Base Sepolia USDC / faucet | Fund the operator wallet now; keep an Anvil fallback |
| Guardian explore eats the clock | Timebox to 45 minutes; if it stalls, use the six-context map in the intent |
| API drift between web and backend | Frozen contract + mocks; integration only at H+9 |
| Judges have no wallet | Demo signer button for the owner signature; MetaMask optional |
| Chain confirmation stalls | Show `pending`, reconcile by receipt; the nullifier makes retry safe |
| Hosted deploy secrets | Testnet keys only; `.env.example`; no secrets committed |
| Audit file not visible | Mount the Rigorix workspace volume into the console; verify early |

## Submission checklist (hard requirements)

- [ ] Public repo in the proximata GitHub organisation, track/team folder.
- [ ] `LICENSE` (MIT) at the repository root.
- [ ] `README.md` with setup, run, environment, architecture, assumptions.
- [ ] `.env.example` with no secrets.
- [ ] Code the jury can run from the README.
- [ ] 3-minute demo video, end to end.
- [ ] Written submission: title, one-line pitch, team, problem, solution, stack, links.
- [ ] Optional: live demo URL, pitch deck.

## Analyst gates — what gets reviewed

| Gate | Review question |
|---|---|
| G0 | Does the context map still support all seven scenarios? Are must/should/stretch explicit? |
| G1 | Does the UI show the five attempt states without a backend? Does the refusal name a rule? |
| G2 | Is the refused step's tool provably never called? Is the envelope verified in the browser? |
| G3 | Is the approval bound to the exact intent? Is the wrong signature refused? |
| G4 | Does a direct contract call bypassing the app still fail on allowlist or nullifier? |
| G5 | Can a judge reproduce from the README in one command? Is the video honest about Anvil vs Base? |
