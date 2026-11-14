# Bursar — 3-minute pitch video

File: `docs/bursar-pitch.mp4` — 1920×1080, H.264/AAC, 2:49, recorded from the running demo stack
with a real payment on Anvil. The narration is synthesized; the caption text below is the same script
if you want to re-voice it.

## The story in one line

The agent can propose any payment; Rigorix is the only execution path; every attempt — allowed or
refused — is checked at the moment of sending and sealed in a signed envelope.

## Shot list

| Time | Picture | What it proves |
|---|---|---|
| 0:00 | Title card: *Ask. Watch the gate.* | The pitch, in five seconds. |
| 0:05 | Capacity page, €30 free. Ask: "pay the energy bill 20". | A sentence becomes a real bill and proposal. |
| 0:16 | **PAID** card. Rigorix step passes, capacity drops to €10, tx link. | The gate executed: approval, payee, capacity all passed. |
| 0:29 | Independent explorer: transaction `0x82f7…`, Success, 20 USDC treasury → Wien Energie, block 141. Then the USDC token page. | The crypto ledger is real and readable from outside the app. |
| 0:56 | Ask: "pay energy 11". **NOT SENT** card; spending-limit finding; "Signed, never sent". | Rigorix refuses at the moment of sending; nothing moves. |
| 1:06 | Click **Verify in browser**; expand the envelope JSON. | The refusal is signed evidence with rule, exit code and digests. |
| 1:26 | Precondition page. Reset. Ask for €20 above a €15 approval line → approval card. | Approval is a request, not a durable grant. |
| 1:38 | Freeze Wien Energie → "payee frozen — the check will refuse". | The operator's authority lives outside the agent. |
| 1:43 | **Sign & send** → **STOPPED BY RIGORIX**; payee check failed, approval passed. | The owner approved; the gate still stopped the payment. |
| 1:51 | Verify the refusal envelope; read the finding digests. | The refusal is evidence, not an error message. |
| 2:16 | The trail: three chained envelopes, "chain intact", prev-hash match. | Every governed run is linked and verifiable. |
| 2:43 | End card: *One execution path. A signed record of every attempt.* | The claim. |

## Narration

**Intro (over the paid run).** Bursar is a household agent that pays real bills in USDC, and cannot
move a cent on its own. It proposes. Rigorix executes. Every send goes through the governed step,
which checks the owner's rules at the moment of sending, and signs the decision: allowed, or refused.
Here the cap is thirty euros a day. We ask for the energy bill: twenty euros. The gate checks
approval, payee, and capacity. It passes, the transaction is broadcast, and ten euros remain.

**The ledger.** This is the chain, from an independent explorer. Twenty USDC moved from the household
treasury to Wien Energie, confirmed in block one hundred forty. The token view shows the same ledger
from the other side: the money left the household, and the payee received it.

**The refusal.** The next bill is eleven euros. With ten free, it does not fit. Rigorix still runs the
governed step, and its capacity check refuses at the moment of sending. The payment was signed, never
broadcast; no money moved, and the ledger did not change. The refusal is evidence: a signed envelope
with the rule, the exit code, and the digests of the check and the authority. The browser verifies it
without trusting the server.

**The verification.** The browser verifies the HMAC signature and the envelope schema. The findings
carry the digests of the check and of the authority file — proof of exactly which rule refused this
payment, and of who wrote it.

**The precondition.** Approval is not authority. Now the cap is thirty, with a fifteen-euro approval
line, and we ask for twenty. It fits, so it needs the owner's signature. The owner signs, then the
operator freezes that payee. At the moment of sending, Rigorix re-reads the operator's file, and
refuses. The owner approved; the network still stops the payment. The card shows the check that
failed, and the approval that passed before it. Nothing was broadcast.

**The trail.** Every governed run is chained: each signed envelope carries the hash of the one before
it. The trail verifies that chain in the browser, and every refusal can be inspected down to its
findings. That is the product: one execution path, checked at the edge, and a signed record of every
attempt. Bursar. Ask, and watch the gate.

## Recording setup

- Stack: `docker compose up -d` plus the Rigorix container profile; explorer on `:4000`.
- World before the take: cap €30, approval line €30, all payees active, ledger and trail cleared.
- The €20 payment runs immediately; the €11 attempt is refused by the capacity precondition.
- The precondition take resets to €30/€15 (apply & reset), asks €20, freezes Wien Energie, then signs
  and sends — refused by the payee precondition.
- The trail therefore shows three executions: paid, capacity-refused, payee-refused.
