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

The app is **console-first with a mock fallback**. It reads the live console surface at
`http://127.0.0.1:8000` with a bearer token:

```
GET  /v1/console/constitution
GET  /v1/console/approvals
GET  /v1/console/bills
GET  /v1/console/evidence
GET  /v1/console/evidence/{id}/verify
POST /v1/console/approvals/{id}/signature
GET  /readyz
```

If the console is not up (or `VITE_FORCE_MOCK=1`), it uses the fixtures in `src/data.ts` and
labels itself `demo data` in the header. Live rows are merged on top of the demo world so the
story and Control Room stay explorable while the approval, bills and evidence are real.

```bash
# live console must be running on :8000
npm run dev

# pure design/demo run, no network
VITE_FORCE_MOCK=1 npm run dev
```

## Environment

Copy `.env.example` to `.env.local` (already present for local runs).

| Variable | Default | Purpose |
|---|---|---|
| `VITE_CONSOLE_API_URL` | `http://127.0.0.1:8000` | Console API base (browser-facing surface). |
| `VITE_OWNER_TOKEN` | `demo-owner-token` | Demo bearer token from the console auth matrix. |
| `VITE_FORCE_MOCK` | `0` | `1` = never call the console; use fixtures. |

## What is real, what is demo

- **Live approvals:** the attention card is `GET /v1/console/approvals[0]`. Signing POSTs the
  signature bytes to `/v1/console/approvals/{approval_id}/signature` (the console's only write,
  forwarded unmodified to Authority). The demo signer is used because Authority's typed-data
  document is not exposed on the console surface; the card says so.
- **Live bills:** `GET /v1/console/bills` is mapped onto the feed (SETTLED → paid, RECEIVED →
  planned, REFUSED → refused). A bill with a pending approval is shown once, as waiting — never
  as both paid and waiting.
- **Live constitution:** `GET /v1/console/constitution` sets the daily cap and signature
  threshold shown in the masthead and rules panel.
- **Live evidence:** `GET /v1/console/evidence` attaches its envelope to the live intent;
  **Verify** calls `GET /v1/console/evidence/{id}/verify` and renders the service's verdict
  (`verified` / `tampered` / `unknown`), not a client-side guess.
- **Story and Control Room:** always a local simulation layered on today's state, and labelled
  as such. They never reset the console and never pretend a simulated settlement is live.
- **Demo-only world:** the extra payees/refusals from `src/data.ts` remain so the story, feed,
  and lab are fully populated offline.
- **Amounts:** the demo uses a 1:1 EUR/USDC display for legibility. Console decimal strings are
  converted to micro-units at the boundary.

## Backend integration notes

- The console has no deny, freeze, or scenario endpoints. **Deny** is a local refusal (no
  dispatch happens; Authority keeps the intent until it expires). Freeze lives in the Control
  Room sandbox.
- The console exposes evidence records and a verdict, not the raw envelope bytes; the browser
  verifier is therefore only used for demo envelopes.
- CORS for `http://localhost:5173` and `http://127.0.0.1:5173` is already configured in the
  console deployable (`backend/src/apps/shell.py`).
- If any endpoint is missing, the UI falls back to the fixtures and labels itself `demo data`.

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
  api.ts                  console client + mapper, signature passthrough, evidence verdict
  data.ts                 contract types, fixtures, formatting, envelope preview
  styles.css              the design system
  components/
    TopBar, Attention, StoryRail, Lab, Feed, Constitution, EvidenceDrawer
```

## Non-goals

- No trading, price prediction, or speculation.
- The bank payout is simulated and labeled.
- No production secrets; the demo HMAC key and signer are test-only.
