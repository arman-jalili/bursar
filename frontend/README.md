# Bursar — frontend

The owner-facing console for **Bursar**, the family bursar: an agent pays the household bills,
the constitution decides, and every decision leaves a signed receipt.

This is design direction **A — Gumroad Editorial**, restructured for usability: the page opens
with the one thing that needs the owner, then a guided story that runs the exact demo scenarios,
then the agent's day, then the rules that decided.

## The first 30 seconds

1. **“Needs you now”** — the €240 dentist approval is inline: amount, payee, invoice, intent,
   nonce/deadline, **Sign & approve** / **Deny**, and a four-step “what happens when you sign.”
2. **“The 3-minute story”** — five scenes: normal bill → scam invoice → split cap → new payee →
   freeze. Each scene has a caption and a **Next scene** button. No hidden demo drawer.
3. **“The agent's day”** — a readable timeline of paid/refused attempts. Click any row to open
   its receipt.
4. **“The Constitution”** — the rule that refused the last attempt is highlighted, with a link
   to that evidence.
5. **Receipt drawer** — the envelope JSON, **Verify**, **Flip a byte**, tx, anchor, and the
   consequence (“no transaction” for a refusal).
6. **The control room** — a sandbox with the same decision logic: pick an experiment (scam,
   split, new payee, normal), move the levers (daily cap, per-payee cap, signature line,
   bank-change guard, new-payee rule, freeze), and **Run / Repeat experiment**. The result shows
   the verdict, the rule that decided, and a before/after note: *“The invoice did not change. The
   rule did.”*

## The control room

The lab is deliberately separate from the live feed, and labels itself a simulation. It exists to
answer the judge’s question: *why did that payment get through or get refused?*

Try this:

1. Run the **Scam invoice** experiment → `REFUSED · bank_digest_mismatch`.
2. Turn **Bank-detail change → refuse** off.
3. Press **Repeat experiment** → `ALLOWED · bank_digest_mismatch_disabled`, with the note
   “This is how a scam gets paid.”
4. Turn the guard back on, switch to **Split invoice**, and raise the daily cap above €566.30 →
   the fifth invoice is allowed. Lower it again → refused.
5. Switch to **New payee**, lower the signature line, toggle the new-payee rule, and freeze the
   dentist. Each lever changes the verdict and names the rule.

The same invoice, the same amount, the same payee. Only the world changed.

Deep teal-green is the sandbox color: the Control Room border, badge, active experiment tab,
and **Run experiment** button, with a black outline and offset shadow. Product actions stay pink;
refusals stay red; verified stays green.

## Run

```bash
npm install
npm run dev        # http://localhost:5173
npm run build
npm run preview
```

The app is **API-first with a mock fallback**. It calls `GET /api/state`, `GET /api/attempts`
and subscribes to `/api/events`. If the console API is not up, it uses the fixtures in
`src/data.ts` and labels itself `demo data` in the header.

Pure design/demo run without API 404s:

```bash
VITE_FORCE_MOCK=1 npm run dev
```

## Environment

Copy `.env.example` to `.env.local`.

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE` | `/api` | Console API base. Public contract: `docs/BURSAR-BUILD-CONTRACT.md`. |
| `VITE_FORCE_MOCK` | `0` | `1` = never call the API; use fixtures. |
| `VITE_DEMO_HMAC_KEY` | `bursar-demo-hmac-key` | Demo key for browser envelope verification. Testnet/demo only. |

## What is real, what is demo

- **Contract shapes:** `Attempt`, `Policy`, `ApprovalRequest`, statuses and decision sources
  mirror the frozen contract.
- **Browser evidence:** when the API returns an envelope, **Verify** calls
  `rigorix-verifier/browser` (`verifySignature` + `validateEnvelope`) with WebCrypto. In mock
  mode it simulates and says so. The receipt drawer fetches the live envelope from
  `/api/attempts/:id/envelope` when the console API is up.
- **Owner approval:** if `window.ethereum` exists, the attention card signs EIP-712 typed data
  and POSTs `/api/attempts/:id/approve`; otherwise it uses a clearly labeled demo signer.
  After approval it reloads `/api/state` and `/api/attempts` so the receipt is the backend's.
- **Story scenes:** with the API up, each scene calls `POST /api/scenarios/:id` and reloads the
  state; if the API is unavailable, it falls back to the local simulation and labels the source
  `demo data`. The lab is always a local sandbox and says so.
- **Amounts:** the demo uses a 1:1 EUR/USDC display for legibility. The chain settles USDC; the
  receipt and chain card name the rail.

## Backend integration checklist

- `GET /api/state` should include `approval` for the pending attempt, or the SSE
  `approval.requested` event must carry the exact `ApprovalRequest` (intent, payee, amount,
  nonce, deadline, EIP-712 domain/types/message). Without it the UI can only use the demo
  approval fixture.
- `POST /api/scenarios/:id` should accept `reset` plus `normal`, `poisoned`, `split`,
  `new-payee`, `freeze`. If `reset` is missing, the story falls back to the local simulation.
- `GET /api/attempts/:id/envelope` must return the raw Rigorix envelope. The drawer fetches it
  and the Verify button runs `rigorix-verifier/browser` against it.
- `POST /api/attempts/:id/approve` receives `{ signature, ownerAddress, nonce, deadline }` and
  should return the updated attempt/state; the UI reloads `/api/state` and `/api/attempts`.
- SSE event names: `attempt.updated`, `capacity.updated`, `approval.requested`, `chain.updated`.
- If any endpoint is missing, the UI falls back to the local simulation and labels itself
  `demo data`; it never pretends a simulated settlement is live.

## Demo story

| Scene | What it shows |
|---|---|
| 1 · Normal bill | Agent pays; USDC settles; receipt appears. |
| 2 · Scam invoice | Bank digest mismatch; refused at dispatch; **no transaction**. |
| 3 · Split cap | Six small invoices; the daily cap refuses the fifth. |
| 4 · New payee | €240 dentist; waits for the owner's EIP-712 signature. Sign, then continue. |
| 5 · Freeze | Payee frozen after approval; dispatch re-reads and refuses. |

Policy in the fixtures: daily cap **€500**, per-payee **€400**, approval over **€100**.
€116.30 committed leaves €383.70; the €240 dentist waits; the fifth €90 split invoice would
make €566.30 and is refused.

## Structure

```
src/
  App.tsx                 composition + story state machine + scenario mutations
  api.ts                  API-first client, SSE, browser verification, EIP-712
  data.ts                 contract types, fixtures, formatting, envelope preview
  styles.css              the design system
  components/
    TopBar, Attention, StoryRail, Lab, Feed, Constitution, EvidenceDrawer
```

## Non-goals

- No trading, price prediction, or speculation.
- The bank payout is simulated and labeled.
- No production secrets; the demo HMAC key and signer are test-only.
