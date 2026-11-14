# Demo UX — what to change, and why

Written after a walkthrough complaint: *"nobody understands what is going on here, or where to
click, and when 'Run experiment' is clicked it is not clear what is going on"* — plus a
fact-check of the README, which says an agent proposes payments. **There is no agent.** There is
an API token (`demo-agent-token`), a `key_id` field, and a seed script that calls `dispatch`. No
process proposes anything.

Both complaints have the same root cause: the demo is organised by **architecture**, and it
narrates rather than asks the user to do something. Fixing the pixels without fixing the
organisation will not help.

---

## 1. Diagnosis (evidence, not taste)

| symptom | evidence |
|---|---|
| The page opens with a marketing headline, a narration rail, a "story" rail, a "lab", then a feed | `App.tsx` order: masthead → narration → Attention → StoryRail → Lab → feed-layout |
| Nothing tells you what to do first | five sibling sections, no primary action, no steps |
| "Run experiment" is a **client-side simulation** sitting next to real live data | `Lab.tsx` computes the result locally from levers (`freezeDentist`, …); it makes no HTTP call |
| It is impossible to tell real from simulated | the simulator and the live feed share one visual language and one screen |
| "The agent proposes" is false | no loop, no scheduler, no proposer; README line 3 |
| The engine's presence is a strip, not a step in the flow | `EngineStrip` is a status bar |

The single most damaging item is the third: a simulation that looks like the product, on the same
screen as the product, makes **everything** look simulated. That is why the reviewer cannot tell.

---

## 2. The product sentence

> **A household gave an automation permission to pay its bills. Every payment is checked against
> the owner's rules before money moves, and every payment leaves a receipt the owner can verify
> without trusting us.**

Three actors, and the UI must always say which one is acting:

| actor | what it can do | how the UI names it |
|---|---|---|
| **proposer** | proposes a payment from an invoice | "proposed 2 min ago by <name>" |
| **owner** (you) | approves, signs, freezes a payee | "you" |
| **engine** | allows, escalates, refuses — with a rule id | "authority" + rule code |

### Decision required: is the proposer an agent or a runner?

Two honest options; pick one before rewriting copy.

- **A. Build the agent (recommended, ~50 lines).** `scripts/agent.py`: read unpaid invoices →
  create a proposal → POST it. Runs on demand (a button "Run proposer" in the demo header) or by
  cron. The story becomes true, and the demo gains its most interesting moment: *the agent
  proposes three bills, one of which the engine refuses.*
- **B. Relabel.** "An automation proposes" / "a scheduled runner". Nothing is built; the README and
  UI stop claiming an agent exists.

Everything below works with either, but the copy differs. With A, the flow has three beats; with B,
two.

---

## 3. New information architecture: one spine, three surfaces

Delete the current page. Replace with:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Bursar · Weiss household        [engine ● live 12 ms ▾]      [Advanced ▾]│
├──────────────────────────────────────────────────────────────────────────┤
│  INBOX                                                    2 need you     │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ Zahnarzt Dr. Holzer          €240.00   needs your signature   →    │  │
│  │ Wien Energie                 €84.20    ready to pay            →   │  │
│  │ Apotheke Heiligen Geist      €48.50    refused · C-6 quarantine    │  │
│  │ Hausmeister Berger           €60.00    refused · P-2 payee frozen  │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│  Today: cap €500 · committed €0 · reserved €384.20 · left €115.80        │
└──────────────────────────────────────────────────────────────────────────┘
```

Surfaces:

1. **Inbox** (default) — every bill, one line, one status, one arrow. This is the whole product
   for 90% of the demo.
2. **Payment sheet** — the drawer that opens from a row. It is the only place with buttons that
   change the world. It has two faces: **Review** (before) and **Receipt** (after).
3. **Advanced** — hidden behind the header toggle. Contains everything technical that exists
   today: the raw call inspector, the engine JSON, the evidence envelopes, the verifier. Advanced
   is where a sceptic goes; it must not be the front door.

---

## 4. The payment sheet — the only screen that matters

Opened by a row. Four numbered blocks, always the same order, always all four, so the second time
you look you know where to look.

### Review face

```
1  THE BILL
   Zahnarzt Dr. Holzer · invoice INV-2291 · €240.00 · due 16 Nov
   proposed 2 min ago by runner ← names the proposer, always

2  YOUR RULES                                              constitution v3
   ✓ C-1  payee is known and not frozen
   ✓ C-3  inside the daily cap     €384.20 + €240.00 ≤ €500.00
   ✗ C-5  above €100 needs your signature
                     ↑ clicking opens the rule text; this is where the engine becomes legible

3  DECISION                                      authority-service · 12:04:11
   ESCALATE — owner signature required            reason A-15
   correlation 3eb74734…

4  [ Sign and pay ]                    ← the only primary button on the screen
```

For an allowed bill, block 4 is `[ Pay €84.20 ]`. For a refused one there is no 4 — there is a
sentence: *"Nothing will be paid. The engine refused at 12:04; you can unfreeze the payee and it
will be re-checked."* with `[ Unfreeze payee ]` as the secondary action, naming what unblocks it.

### Receipt face (same drawer, after the action)

```
✓ PAID €240.00 · 12:04:19
   chain    anvil · block 6
   tx       0x2ac4…b7b4                            [ explorer ↗ ]
   anchor   Anchored(orderId, nullifier)           ✓ found in receipt

   engine   Rigorix execution 01a1d7bc… · evidence complete
   command  payments.broadcast --raw-tx 0x02f8…    [ copy ]
   audit    envelope + anchor                      [ verify in your browser ]

   ordered  12:04:11.871   signed  12:04:11.882 (hash persisted)   broadcast 12:04:19
                                              ↑ the ordering, on screen, with timestamps
```

Every line in the receipt is a claim with a handle: explorer link, copy button, or in-browser
verification. Nothing is a badge without a source.

---

## 5. The three unfakeable moments

This is how "the engine actually runs" becomes obvious instead of asserted. Each is a *step in the
flow*, not a status bar.

1. **The rules panel names the rule that fired.** A refusal shows `C-6 quarantine`, not "failed".
   Changing one input and watching the decision change (allow ⇄ escalate ⇄ refuse) is only
   convincing if the rule id and the correlation id come from the server — so they must.
2. **Verify in your browser.** `rigorix-verifier/browser` is already a dependency and unused.
   Wire `verifyLedgerReceipt` / `verifyHistorySlice` / `validateEnvelope` against a pinned Ed25519
   public key shown in the panel. Add **[ tamper ]**: flip one byte → `✗ INVALID`. One flipped
   byte turning PASS into FAIL in front of the audience ends the "is this real?" conversation.
3. **The what-if goes through the real engine.** The current Lab computes locally, which is why it
   reads as fake. Replace it with a request to the real authority service (a `simulate` flag that
   persists nothing) and display its correlation id. Now even the playground is engine-answered.

Prerequisite for 2: the backend must expose fetchable proofs —
`GET /v1/proofs/{execution_id}` (proxy `rigorix.audit.read`) and `GET /v1/proofs/public-key`.
Today the only handle is `rigorix://audit/…`, which no browser can open.

---

## 6. Delete / rename

| today | verdict |
|---|---|
| masthead marketing headline + narration rail | **delete** — the product is the inbox |
| `StoryRail` ("story" steps) | **delete** — it narrates instead of asking |
| `Lab` with `Run experiment` + levers | **demote + relabel**: `Advanced → What-if`, and make it call the real engine |
| `Feed` as a separate section | **merge into Inbox** (it is the same list with history) |
| `EngineStrip` as a global bar | **shrink into the header** (`● live 12 ms ▾` → raw JSON) |
| "Run experiment →" | **rename** to `Check this bill` / `Ask the engine` — a verb that says what happens |
| README "the agent proposes" | **fix** (see §2 decision) |
| `demo-agent-token` in the docs without an agent | rename to `demo-runner-token`, or give it a real caller |

Rule for every future element: **if it cannot name its source (endpoint, rule id, signature, tx
hash), it does not go on the primary screen.**

---

## 7. Build plan

| phase | content | why first |
|---|---|---|
| **P0** | Inbox + payment sheet (review face) + header engine dot + delete masthead/narration/StoryRail/Lab from the front page; fix README claims | this alone fixes "where do I click" and "what does this do" |
| **P1** | Receipt face + proof buttons + `GET /v1/proofs/{id}` + in-browser verify with tamper | turns "engine in background" into something the reviewer checks |
| **P2** | `Advanced` drawer: call inspector move-in, what-if via real engine, evidence envelopes | gives the sceptic a room without cluttering the demo |
| **P3** | proposer: real `scripts/agent.py` (or relabel) + "Run proposer" button | makes the story literally true |

Component sketch (files):

```
frontend/src/routes/Inbox.tsx          one list, one status per row
frontend/src/routes/PaymentSheet.tsx   Review | Receipt, numbered blocks
frontend/src/routes/Advanced.tsx       inspector, engine JSON, proofs, what-if
frontend/src/components/RuleCheck.tsx  ✓/✗ row + rule id + "why" expansion
frontend/src/components/Verify.tsx     verifier + pinned key + tamper
```

`App.tsx` becomes a router with two real routes and one drawer. No rails, no narrative.

---

## 8. The 90-second demo script (target)

1. Land. One list, four bills, two need you. *"This is the household's inbox."*
2. Click **Wien Energie €84.20**. The sheet shows the bill, three rule checks, `ALLOW`, and one
   button. *"Nothing moves until I press this."*
3. Press **Pay**. Receipt appears: tx hash, `Anchored` found in the receipt, Rigorix execution id.
4. Click **verify in your browser** → `✓ valid`, key fingerprint. Click **tamper** → `✗ INVALID`.
   *"The page checked a signature with a key I pinned, not one the server handed it."*
5. Back. Click **Zahnarzt €240** → `ESCALATE — signature required` → **Sign and pay**.
6. Back. Point at the two refused rows. *"These never reached a button. C-6 quarantine, P-2 frozen
   — the engine refused them before I could pay."*
7. Open **Advanced** only if asked. *"Here is every call the page made, with a curl."*

Nothing in that script requires reading the README, and every claim is one click from its proof.