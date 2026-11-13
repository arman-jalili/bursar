# Ubiquitous Language

> Canonical glossary for **bursar**.
> All code MUST use these terms. Aliases/synonyms listed below are **prohibited** in source identifiers.
> Drift is detected by `.pi/scripts/validate-ubiquitous-language.sh`.

## Glossary

| Term | Definition | Bounded Context | Aliases/Synonyms | Examples |
|------|-----------|----------------|-----------------|---------|
| owner | The adult child who funds the account and authors the constitution. The only party who can change rules, add payees or approve exceptions. | Mandate | operator-of-record, account holder | Owner signs an EIP-712 approval for a new dentist payee. |
| payer | The parent whose bills are being paid. Receives the service, holds no keys, signs nothing. | Mandate | beneficiary | Payer sees a read-only list of settled bills. |
| agent | Software identity that may only propose payments. Holds no keys and cannot edit policy or command paths. | Mandate |  | Agent proposes five attempts for the same utility invoice. |
| mandate | The scoped, revocable grant of authority from owner to agent, pinned to one constitution version lineage and one household. | Mandate | delegation | The mandate permits paying enrolled payees up to 50 USDC/day. |
| constitution | The operator-owned rule set the enforcement layer checks: caps, thresholds, allowlist, signature requirements. Immutable per version, append-only lineage. | Mandate | policy, .rigorix config | Constitution v3 raises the per-payment threshold to 100 USDC. |
| payee | A registered biller with a verified payout address, a verified bank digest and an eligibility status. | Mandate | biller, merchant | The pharmacy is a payee in status eligible. |
| bank digest | Hash over payee routing details. Replaces raw account numbers in every downstream check; a mismatch is the bank-detail-change scam signal. | Mandate | routing hash | Invoice presents digest 9f2c… but the payee's verified digest is 41ab… |
| quarantine | Payee-level suspension triggered automatically by a bank-digest mismatch; cleared only by an owner re-approval. | Mandate | hold | The scam invoice quarantines the utility instead of redirecting the money. |
| freeze | Owner-initiated payee suspension. Strictly stronger than quarantine and never automatic. | Mandate | block | Owner freezes the insurer after a dispute. |
| cap | The maximum total USDC that may be committed plus reserved within a rolling day, summed across all payees. | Mandate | daily limit | Cap of 150 USDC/day refuses the sixth 40 USDC split invoice. |
| per-payee cap | The maximum USDC that may be committed plus reserved for one payee within a rolling day; a second, narrower ceiling than the daily cap. | Mandate | payee limit | Per-payee cap 80 USDC refuses the third 40 USDC invoice to the same utility. |
| threshold | The per-payment amount above which an owner signature is mandatory, regardless of payee status. | Mandate | auto-pay limit | Threshold 25 USDC; a 320 USDC bill escalates to the owner. |
| invoice | A bill document presented for payment, identified by its content hash, carrying amount, due date and a presented bank digest that is never authoritative for routing. | Billing | bill, statement | The utility invoice for 42.50 USDC due Friday. |
| invoice hash | Canonical content hash of an invoice. Serves as the duplicate key off-chain and the nullifier seed on-chain. | Billing | nullifier seed | Hash 0x8c1f… appears twice → duplicate detected before the funnel. |
| payment attempt | The agent's structured proposal to pay one invoice. Exists only to be judged; it carries no authority and cannot dispatch itself. | Billing | proposal | Attempt 7 for invoice 12, 42.50 USDC, payee utility. |
| agent proposal | When the agent submits, the only accepted shape is a payment attempt; anything else is a proposal rejection, not a negotiation. | Billing |  | A proposal containing a command path is rejected, not sanitized. |
| in-flight | The invoice already has an attempt that has been dispatched or is awaiting signature; a second attempt is refused locally. | Billing | pending | Six split invoices run concurrently; only the first that reserves wins. |
| presented bank digest | The digest of routing details as they appear on the invoice. Compared against Mandate's verified digest; mismatch means quarantine. | Billing | invoice routing details | The poisoned invoice presents an attacker digest. |
| split invoices | One real obligation broken into several invoices each below the threshold. Detected by the aggregate daily cap, not by per-invoice heuristics. | Billing | structuring | Six invoices of 25 USDC against a 150 USDC cap. |
| payment intent | The code-constructed, immutable description of one payment: intent id, invoice id, payee, payee address, amount, bank digest, is_new_payee, requires_owner_signature. The unit of authority and of signature binding. | Authority | intent | Intent 0xab… for 320 USDC to the insurer, requires_owner_signature true. |
| determination | The allow/deny/escalate verdict for one intent, produced at dispatch time against the in-force constitution and live payee state, with reason codes. | Authority | verdict, decision | deny / digital_digest_mismatch / constitution v3 / payee quarantined. |
| reservation | An atomic hold of amount against the daily cap for one intent; committed or released exactly once after settlement resolves. | Authority | hold, capacity reservation | Six 25 USDC attempts against a 150 USDC cap: the sixth is refused. |
| approval | An owner EIP-712 signature over an intent's exact fields; single-use, expiring, and invalid the moment the intent changes. | Authority | owner signature, sign-off | Owner signs the new payee and 320 USDC amount in one typed-data payload. |
| escalate | The verdict for a payment that is not refused but cannot proceed without the owner: new payee or above threshold. | Authority | escalation, needs signature | escalate / new_payee / requires_owner_signature true. |
| moment of consequence | The instant a precondition check is bound to the dispatch. Authority must re-read all external state here, not at plan time. | Authority | dispatch time, check point | Payee frozen between approval and dispatch → refused at this moment. |
| committed | Spend that has been confirmed on-chain and permanently counts against the day's cap. | Authority | spent | Two settled invoices, 85 USDC committed. |
| release | Returning reserved capacity to the ledger because the payment provably did not happen. Never a rollback of committed spend. | Authority | unreserve | Chain revert releases the 42.50 USDC reservation. |
| is_new_payee | Flag on the intent, derived from Mandate's payee status, that forces escalation regardless of amount. | Authority |  | First payment to the dentist is new → escalate. |
| requires_owner_signature | Flag on the intent that the contract also checks on-chain; the off-chain determination and the contract must agree. | Authority |  | Set true for new payees and above-threshold amounts. |
| settlement | The confirmed on-chain movement of USDC from the household account to a payee address under one nullifier. | Settlement | payment execution | 42.50 USDC settled in tx 0x3d… on Base Sepolia. |
| settlement order | The immutable executable form of an allowed intent, carrying payee address, amount, nullifier and the code-generated command reference. | Settlement | order | Order 12 derived from intent 0xab… |
| nullifier | Derived once-only marker from the invoice hash; the on-chain anti-double-pay key. Spending it twice is impossible by construction. | Settlement | spent marker | Replaying invoice 12 hits a spent nullifier and reverts. |
| receipt | The chain proof for an order: tx hash, block, confirmations, status, and the anchor written for its evidence envelope. | Settlement | chain receipt, proof | Receipt confirms 6 blocks and anchor tx 0x9e… |
| commit-point lock | The property that PaymentRouter, not the app, is the final gate: whatever the off-chain state, a bad payment cannot be mined. | Settlement | second lock, on-chain lock | A stolen operator key still cannot pay a frozen payee address. |
| confirmation | Blocks mined after the transaction's inclusion; only after the required count is the settlement final and the cap committed. | Settlement | finality | Anvil needs 1, Base Sepolia needs 2 for the demo. |
| run_command | The Rigorix payment step: a fixed command path plus structured params generated by code from the intent. | Settlement | payment step | `run_command { command: "/opt/bursar/bin/payctl --intent <id>", intent_id, payee, amount_usdc, bank_digest, ... }` |
| revert | On-chain rejection of a settlement, most often a duplicate nullifier or a failed signature check. Always a refusal with evidence, never a retry. | Settlement | on-chain refusal | Contract reverts with NullifierSpent. |
| anchor | The on-chain write of an envelope hash that gives tamper evidence an independent timestamp. | Settlement | anchor tx | Envelope hash 0x77… anchored in tx 0x9e… |
| evidence envelope | Signed immutable wrapper around one domain fact, containing subject ids, the fact payload, the constitution version consulted and an HMAC. | Evidence | envelope, signed envelope | Envelope for a refusal: deny / payee_frozen / constitution v3. |
| envelope hash | Canonical hash of an envelope including its HMAC; what gets anchored on-chain and re-compared at verification. | Evidence | sealed hash | Flip one byte of the payload → hash no longer matches the anchor. |
| refusal record | A first-class evidence artifact for a denied payment, carrying the reason code and the constitution version that produced it. | Evidence | denial evidence | The poisoned-invoice refusal is demoed as a verified envelope, not an absence. |
| tamper evidence | HMAC proves no one in the operator domain edited the record; the anchor proves the record existed at a point in chain time. | Evidence | integrity, audit trail | Verifier shows verified locally, tampered after an edit. |
| party | One of the three roles in the mandate — owner, payer or agent — each with a fixed capability set. Roles never overlap for the MVP. | Mandate | participant | The agent is a party, but a party that can only propose. |
| in force | The single constitution version currently binding on every determination. Authority must re-read it at dispatch, never cache it. | Mandate | current version, active policy | Constitution v3 is in force when the sixth split invoice is judged. |
| superseded | State of a constitution version that has been replaced. It stays queryable so past determinations can be explained against the rules they actually used. | Mandate | historical version | A refusal citing constitution v2 is provable after v4 is published. |
| eligibility | The derived judgement of whether a payee may be paid right now: eligible, new (escalate), quarantined (refuse) or frozen (refuse). | Mandate | payability | Eligibility flips to quarantined the moment the digest mismatches. |
| verified digest | The bank digest the owner personally approved for a payee. Distinct from the digest an invoice presents, and the only one Settlement may route to. | Mandate | baseline digest, trusted digest | Verified digest 41ab…; presented digest 9f2c… → mismatch. |
| re-approval | The owner-signed act of accepting a new bank digest for a payee and lifting quarantine. | Mandate | digest re-approval | Owner re-approves the utility's new account after a phone call. |

## Adding New Terms

1. Identify the term used in conversation and code
2. Add a row to the Glossary table
3. Define the term's **bounded context** (which module it lives in)
4. List any **aliases/synonyms** that agents might mistakenly use
5. Provide **code examples** showing correct usage
6. Run `.pi/scripts/validate-ubiquitous-language.sh` to detect drift

> **Rule of thumb:** If two agents use different names for the same concept, add an entry.
> The canonical term is the one used in the architecture module documents.

## Term Conflicts (language gaps)

When the same term is used with different meanings by different parts of the business
(e.g. "transaction" = a database transaction for engineers but a statement line for the
business), that is a bounded-context boundary signal — record the conflict here and resolve
it in the exploration review:

| Term A | Term B | Why conflicting | Resolution |
|--------|--------|-----------------|-----------|
| _None unresolved for the MVP._ | | | |
