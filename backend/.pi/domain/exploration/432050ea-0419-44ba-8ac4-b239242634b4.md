---
session_id: 432050ea-0419-44ba-8ac4-b239242634b4
created: 2026-11-13
business_context: "Read .pi/context/prompt.md. Explore the Bursar domain for the Proximata 24-hour hackathon. Produce the domain model, ubiquitous language, context map, aggregates/invariants, domain events, core/supporting/generic classification, risks, and the smallest roadmap that fits the timebox. Do not scaffold code yet."
status: draft
---

# Domain Exploration: 432050ea-0419-44ba-8ac4-b239242634b4

> **Status:** draft — AI-suggested, human-review needed.

---

## Business Context

Read .pi/context/prompt.md. Explore the Bursar domain for the Proximata 24-hour hackathon. Produce the domain model, ubiquitous language, context map, aggregates/invariants, domain events, core/supporting/generic classification, risks, and the smallest roadmap that fits the timebox. Do not scaffold code yet.

---

## Actors & Roles

| Actor | Description | Interactions |
|-------|-------------|-------------|
| Owner | Adult child who funds the account and authors the constitution (caps, thresholds, allowlists). | Creates/revokes mandate, edits constitution versions, signs EIP-712 approvals for new payees and above-threshold amounts, freezes payees, reviews evidence. |
| Payer | The parent receiving the service; no crypto knowledge, never signs. | Read-only: sees which bills are handled and settled; may forward an invoice. |
| Agent | LLM-driven software that proposes payments from invoices. | Proposes payment attempts, never holds keys, never edits policy, never chooses command params — code generates them. |
| Payee | Utility, insurer, pharmacy, home service, dentist receiving funds. | Issues invoices with a bank digest; bank-detail changes trigger quarantine. |
| Adversary | Scammer or prompt injector. | Mutates bank details, splits payments to evade caps, replays invoices, steals an operator key. |
| Operator | Whoever holds the Rigorix operator key that dispatches preconditions. | Runs the governance server; cannot exceed the on-chain backstop (allowlist, caps, nullifier, threshold signature) because the contract is the commit-point lock. The full constitution is enforced by Rigorix + Authority. |

---

## Functional Requirements

| ID | Requirement | Priority | Bounded Context |
|----|-------------|----------|----------------|
| FR-001 | The system shall let the owner create exactly one mandate naming the owner address, payer, agent identity and the in-force constitution version. | critical | Mandate |
| FR-002 | The system shall keep constitution versions immutable and append-only, and shall allow only the owner to publish a new version. | critical | Mandate |
| FR-003 | The system shall reject any attempt to modify the constitution that does not originate from an authenticated owner action; the agent and unauthenticated callers have no write path. | critical | Mandate |
| FR-004 | The system shall record payees with an owner-verified address and a bank digest computed over payee routing details. | critical | Mandate |
| FR-005 | The system shall quarantine a payee when an invoice presents a bank digest that differs from the verified digest, and shall block payments to it until the owner re-approves. | critical | Mandate |
| FR-006 | The system shall allow the owner to freeze a payee, and a frozen payee shall be ineligible at dispatch even if it was eligible at plan time. | critical | Mandate |
| FR-007 | The system shall record invoices with payee reference, amount, currency, due date, invoice hash and the bank digest as presented. | high | Billing |
| FR-008 | The system shall refuse a second payment attempt for an invoice already settled or in flight, and the contract shall independently revert a duplicate nullifier. | critical | Billing |
| FR-009 | The system shall accept agent proposals only as structured payment attempts and shall never accept agent-supplied command paths, payee addresses or caps. | critical | Billing |
| FR-010 | The system shall generate the run_command invocation and its parameters in code from the payment intent, never from LLM output. | critical | Authority |
| FR-011 | The system shall produce an authority determination (allow, deny or escalate) for every payment attempt before dispatch, and shall block dispatch when no allow determination exists. | critical | Authority |
| FR-012 | The system shall re-read the in-force constitution version and live payee status at dispatch time rather than trusting a plan-time decision. | critical | Authority |
| FR-013 | The system shall reserve funds atomically so that committed plus reserved never exceeds either the daily cap or the per-payee cap, and shall refuse any attempt that would breach either. | critical | Authority |
| FR-014 | The system shall escalate a payment to owner signature when the payee is new or the amount exceeds the threshold. | critical | Authority |
| FR-015 | The system shall bind an approval to one exact intent id, amount, payee address and bank digest, and shall invalidate the approval if any of those change. | critical | Authority |
| FR-016 | The system shall verify owner approval signatures as EIP-712 typed data off-chain before dispatch, and the contract shall verify the same signature on-chain. | critical | Authority |
| FR-017 | The system shall commit or release a reservation according to the settlement outcome so the cap ledger stays consistent with the chain. | high | Authority |
| FR-018 | The system shall guarantee a refusal produces no on-chain transaction and no reservation commit, while still being recorded. | critical | Authority |
| FR-019 | The system shall dispatch exactly one PaymentRouter transaction per allow determination using USDC on Base Sepolia, with a local Anvil fallback. | critical | Settlement |
| FR-020 | The system shall record a chain receipt (tx hash, block, confirmations, status) for every dispatched order and expose it for verification. | high | Settlement |
| FR-021 | The system shall prevent an invoice from settling more than once on-chain by nullifier enforcement in the contract and nullifier reconciliation in the service. | critical | Settlement |
| FR-022 | The system shall emit a signed HMAC evidence envelope for every Rigorix execution, including dispatch-time refusals; a plan-time policy denial produces no engine envelope and shall be recorded by the console with its rule id and labeled as not enveloped. | critical | Evidence |
| FR-023 | The system shall anchor each envelope hash on-chain and shall fail verification when any byte of the envelope is altered. | high | Evidence |
| FR-024 | The system shall render for the owner an approval inbox showing the exact intent fields to be signed. | high | Console |
| FR-025 | The system shall render for the payer a read-only view of handled and settled bills with plain-language status and a simulated bank payout label. | medium | Console |

---

## Non-Functional Requirements

| ID | Requirement | Category | Target |
|----|-------------|----------|--------|
| NFR-001 | The system shall decide and dispatch a payment attempt within a bounded latency suitable for a live demo. | performance | Determination returned in under 500 ms p95; end-to-end confirm on Base Sepolia under 30 s, Anvil under 3 s. |
| NFR-002 | No LLM shall appear in the enforcement path. | security | Zero LLM calls between attempt submission and on-chain dispatch, enforced by a test asserting no model dependency in Authority or Settlement. |
| NFR-003 | The system shall keep the agent unable to write to the authority service or the policy files. | security | Precondition client lives outside the agent-writable workspace; agent has no write access to .rigorix/ or the SQLite DB. |
| NFR-004 | The system shall produce tamper-evident evidence with independent on-chain time. | security | 100% of runtime decisions enveloped; plan-time denials recorded with rule id; one flipped byte fails verification; one anchor per demo scene. |
| NFR-005 | The system shall be resilient to duplicate and replayed submissions. | availability | Zero successful second settlements across a replay suite of at least 10 replays. |
| NFR-006 | The system shall expose an API-first boundary so the frontend can be built against mocks in parallel. | maintainability | OpenAPI schema published by hour 6; frontend runs against mocks with no backend changes required at integration. |
| NFR-007 | The domain model shall fit the 24-hour timebox including demo rehearsal. | maintainability | Code freeze met with all 7 acceptance scenarios green and no stretch capability blocking the demo path. |
| NFR-008 | The system shall run locally with no external paid dependency. | availability | Full scenario suite runnable on Anvil plus SQLite on a laptop; Base Sepolia used for the live claim only. |
| NFR-009 | The system shall keep cap accounting exactly consistent with the chain. | maintainability | Committed plus reserved ledger equals on-chain settled total within one confirmation of every transaction, verified by a reconciliation test. |
| NFR-010 | The system shall keep the enforcement path operator-verifiable from the repo and chain-verifiable by a third party. | security | Every precondition, constitution rule and EIP-712 struct readable in the repo; HMAC verification with the operator key; envelope hash independently checkable against the on-chain anchor. |
| NFR-011 | The system shall keep the owner's approval flow usable on a phone in under a minute. | performance | Owner signs an escalated payment in at most 3 taps after opening the notification; measured in the demo run. |
| NFR-012 | The system shall degrade predictably when the chain is unavailable. | availability | RPC failure yields a refusal-or-pending determination with no reservation commit; no attempt is silently dropped. |
| NFR-013 | The system shall keep evidence write cost bounded during the demo. | scalability | Anchoring limited to the demo scenario envelopes; remaining envelopes batched and labeled as batched. |
| NFR-014 | The system shall keep the authority service simple enough for a 24-hour build. | maintainability | Single process, SQLite, no message broker, no background job framework; refusal paths unit-testable without a chain. |
| NFR-015 | The system shall never lose an attempt: every submitted attempt has a terminal state. | availability | Zero attempts in a non-terminal state older than 10 minutes in the demo database after the full scenario run. |
| NFR-016 | The system shall keep the agent's blast radius to proposals only. | security | Agent credentials cannot write payee status, constitution, reservations or evidence; verified by an authorization test matrix. |
| NFR-017 | The system shall keep payer-facing copy free of crypto jargon. | maintainability | Zero terms from the crypto vocabulary list on payer screens; reviewed against the UL glossary before freeze. |
| NFR-018 | The system shall be demonstrable from a clean checkout. | availability | docker-compose or make targets bring up Anvil, authority service and console in under 5 minutes on the demo machine. |

---

## Assumptions

| Assumption | Impact if Wrong | Mitigation |
|------------|----------------|-----------|
| One household, one owner, one payer, one mandate at a time — no multi-tenancy. | Identity and policy scoping logic explodes; mandate/quarantine lookups lose their simple key. | Model household_id as a field everywhere but hardcode a single seeded household for the MVP. |
| Invoices arrive as structured records (seeded fixtures or manual/agent extraction), not a full OCR ingestion pipeline. | Ingestion becomes the biggest build item and squeezes enforcement work. | Treat ingestion as a generic/supporting adapter with a seeded fixture set covering all 7 scenarios. |
| Rigorix OSS rigorix-server is used unmodified; only preconditions.toml, sequence-policy.toml, capacity.toml and signed envelopes are authored by us. | Forking the server costs hours and breaks the 'no LLM in enforcement' claim. | Pin the OSS version in hour 0; spike execute/approve/audit.read against it before writing domain code. |
| The chain adapter can run against local Anvil with a Foundry deploy, so the demo does not depend on live Base Sepolia availability. | If Anvil parity with Sepolia diverges (USDC address, gas, confirmations), the demo passes locally and fails on the live claim. | Deploy PaymentRouter to both networks in hour 0; pin chain id, USDC address and confirmation count per network behind ChainNetwork. |

---

## Bounded Contexts

| Context | Description | Entities |
|---------|-------------|----------|
| Mandate | Owns the household, its parties (owner, payer, agent), the payee registry with verified bank digests, and the immutable constitution versions that define caps, thresholds and approval rules. It is the single source of truth for what is allowed; it never decides a specific payment. Per-context pass COMPLETE: 12 entities (5 aggregate roots, 4 entities, 5 value objects), 8 invariants, 12 domain events, 16 ubiquitous-language terms. | Household,Owner,Payer,Agent,Payee,BankDigest,Constitution,ConstitutionVersion,Cap,Threshold,PayeeStatus,PartyRef |
| Billing | The demand side of the domain: invoices as documents, and payment attempts as the agent's only legal output. Billing owns what is owed and what the agent proposed; it never decides whether a payment is allowed. Its job is to make proposals untrusted, structured and non-duplicable. | Invoice,InvoiceLine,PaymentAttempt,AgentProposal,ProposalRefusal |
| Authority | The decision engine and the system's heart. Turns an untrusted attempt into a PaymentIntent with code-generated parameters, re-reads the in-force constitution and live payee state at the moment of consequence, issues an allow/deny/escalate Determination with reasons, and holds atomic Reservations against the daily cap until settlement resolves. | PaymentIntent,Determination,Reservation,CapLedger,Approval,OwnerSignature |
| Settlement | Moves USDC and proves it happened exactly once. Owns the chain adapter, the PaymentRouter call, the nullifier, and the receipt that reconciles the off-chain ledger with the chain. It is the second lock: even a stolen operator key cannot make it pay a payee the contract rejects, exceed an on-chain allowance, or pay the same invoice twice. | SettlementOrder,ChainReceipt,Nullifier,PayeeAddress,ChainNetwork |
| Evidence | Capture-and-verify context: appends a signed HMAC envelope for every attempt, determination, refusal, approval, settlement and revert, and anchors envelope hashes on-chain. It consumes events from Authority, Settlement and Billing and publishes verification for the console and auditors. It holds no enforcement power — it is a witness, not a guard. | EvidenceEnvelope,EvidenceRecord,Anchor,AuditEntry |
| Console | API/UI composition and read models for owner and payer. No business rules; projects other contexts' state. | PaymentReadModel,EvidenceReadModel,ApprovalInboxItem |

---

## Entities

| Entity | Context | Type | Description |
|--------|---------|------|-------------|
| Household | Mandate | aggregate-root | The single tenancy root: one owner, one payer, one mandate, one constitution lineage. Guards that exactly one in-force constitution version exists. |
| Constitution | Mandate | aggregate-root | Append-only lineage of constitution versions. Publishing a new version supersedes the previous one but never mutates history. |
| ConstitutionVersion | Mandate | entity | An immutable snapshot of operator-owned rules: daily cap, per-payment threshold, payee allowlist policy, signature requirements. Addressed by version number and content hash. |
| Payee | Mandate | aggregate-root | A biller with a payout address and a verified bank digest, plus an eligibility status (new, eligible, quarantined, frozen). Eligibility transitions are only legal here. |
| BankDigest | Mandate | value-object | Deterministic hash over payee routing details (account, routing, scheme). Two equal digests mean identical destination; a mismatch is the scam signal. |
| PayeeStatus | Mandate | value-object | Closed set: new, eligible, quarantined, frozen. Encodes whether Authority may allow, must escalate, or must deny. |
| Invoice | Billing | aggregate-root | A bill presented for payment: issuer reference, amount, currency, due date, content hash, presented bank digest, and lifecycle (received, proposed, in-flight, settled, refused, void). Owns the at-most-one-attempt rule. |
| PaymentAttempt | Billing | entity | The agent's structured proposal for one invoice: attempt id, amount, payee reference and the determination reference. The only artifact the agent can create; carries no authority of its own. |
| InvoiceHash | Billing | value-object | Content hash over the normalized invoice document. Doubles as the duplicate key and the seed of the on-chain nullifier. |
| BilledAmount | Billing | value-object | Positive USDC amount with fixed precision; refuses negative, zero, or over-precision values at construction. |
| AttemptStatus | Billing | value-object | Closed lifecycle: proposed, escalated, approved, dispatched, settled, refused, expired. Transitions are one-way. |
| PaymentIntent | Authority | aggregate-root | The canonical, code-constructed description of one payment: intent id, invoice id, payee, payee address, amount, bank digest, is_new_payee, requires_owner_signature. This exact structure is what the owner signs and what the contract checks. Immutable once issued. |
| Determination | Authority | aggregate-root | The verdict for one intent: allow, deny or escalate, with machine-readable reason codes, the constitution version consulted, the payee status read, and the timestamp of the re-read. Immutable evidence of judgement. |
| CapLedger | Authority | aggregate-root | Per-day ledger of committed and reserved totals across all payees. The single aggregate that makes cross-invoice structuring impossible. |
| Reservation | Authority | entity | A hold of a specific amount for a specific intent against a specific day. Moves reserved → committed or reserved → released exactly once. |
| Approval | Authority | entity | An owner signature request and its verified EIP-712 proof, bound to one intent's exact fields, single-use and expiring. |
| OwnerSignature | Authority | value-object | EIP-712 signature bytes plus the recovered signer; valid only if the signer equals the mandate owner and the typed-data digest matches the intent. |
| DeterminationVerdict | Authority | value-object | Closed set: allow, deny, escalate. Deny carries a reason code (digest mismatch, payee frozen, cap exceeded, duplicate, approval invalid). |
| Money | Authority | value-object | USDC amount with chain precision and explicit arithmetic that refuses to lose or invent units during reservation math. |
| SettlementOrder | Settlement | aggregate-root | The executable instruction derived from one allowed intent: intent id, invoice id, payee address, amount, nullifier, network, and the code-generated command reference. Owns the at-most-one-transaction rule. |
| ChainReceipt | Settlement | entity | On-chain proof of a settlement attempt: tx hash, block number, confirmations, status (pending, confirmed, reverted), gas, and the anchor tx hash when one was emitted. |
| Nullifier | Settlement | value-object | Deterministic identifier derived from the invoice hash (plus mandate scope). Spent-once marker mirrored by the contract's own mapping. |
| PayeeAddress | Settlement | value-object | Checksummed EVM address validated at construction; the only destination Settlement will ever encode into a transfer. |
| ChainNetwork | Settlement | value-object | Base Sepolia or local Anvil, with chain id, contract address, USDC address and confirmation requirement bound to it so a receipt always knows where it lives. |
| SettlementStatus | Settlement | value-object | Closed set: ordered, submitted, pending, confirmed, reverted, abandoned. Drives the single commit-or-release decision in Authority. |
| EvidenceEnvelope | Evidence | aggregate-root | Immutable signed wrapper around one domain fact: event type, subject ids (intent, invoice, payee), the fact payload, constitution version consulted, actor, timestamp, and the HMAC over the canonical encoding. |
| Anchor | Evidence | entity | The on-chain write of an envelope hash: tx hash, block, chain id, and the anchored hash. Gives independent integrity and time that no operator can backdate. |
| EnvelopeHash | Evidence | value-object | Canonical hash of the envelope including its HMAC; the exact value written to the chain and compared at verification. |
| VerificationResult | Evidence | value-object | verified, hmac_mismatch, anchor_mismatch or unanchored, with the failing field named so the console can show precisely what broke. |
| Owner | Mandate | entity | The adult child: the only party with rule-changing and exception-approving authority, identified by an EVM address whose signature is checked against every approval. |
| Payer | Mandate | entity | The parent whose bills are paid. Identity matters for display and consent, but the payer holds no keys and can never authorize anything. |
| Agent | Mandate | entity | The software identity permitted to propose payments. Registered here so Authority can attribute proposals and deny everything else it might attempt; holds no signing material. |
| Cap | Mandate | value-object | The daily USDC ceiling applied across all payees in the household, carried on a constitution version. Rejects negative or zero values at construction. |
| Threshold | Mandate | value-object | The per-payment amount above which an owner signature is mandatory, carried on a constitution version. Must be less than or equal to the Cap. |
| PartyRef | Mandate | value-object | A typed reference to owner, payer or agent capturing the role and its identifier, so events can say who acted without embedding a whole party record. |

---

## Domain Events

| Event | Context | Description | Triggered By |
|-------|---------|-------------|-------------|
| MandateCreated | Mandate | A household mandate exists with owner, payer, agent and first constitution version. | CreateMandate |
| ConstitutionVersionPublished | Mandate | A new immutable rule set is in force; the previous version is superseded. | PublishConstitutionVersion |
| PayeeRegistered | Mandate | A payee with a verified address and bank digest entered the allowlist as new. | RegisterPayee |
| PayeeDigestChanged | Mandate | An invoice presented routing details that differ from the verified bank digest. | QuarantinePayee |
| PayeeQuarantined | Mandate | Payee is ineligible until the owner re-approves the new routing details; any in-flight intent for it must fail at dispatch. | QuarantinePayee |
| PayeeFrozen | Mandate | Owner suspended a payee; it cannot be paid at all until unfrozen. | FreezePayee |
| PayeeReapproved | Mandate | Owner signed off on the new bank details; the digest baseline is replaced and the payee returns to eligible. | ReapprovePayee |
| InvoiceRecorded | Billing | A bill entered the system with its hash, amount and presented bank digest. | RecordInvoice |
| DuplicateInvoiceDetected | Billing | An invoice hash already known arrived again; the second one is not treated as new demand. | RecordInvoice |
| PaymentProposed | Billing | The agent produced a structured attempt for an invoice; this is the request that Authority must judge. | ProposePayment |
| ProposalRejected | Billing | The proposal was malformed or carried forbidden fields and was rejected before any determination was requested. | ProposePayment |
| AttemptDispatched | Billing | An attempt moved to dispatched after an allow determination; recorded locally for lifecycle only, settlement truth lives in Settlement. | DispatchPayment |
| InvoiceSettled | Billing | The invoice is closed as paid and can no longer generate attempts. | SettleOnce |
| AttemptRefused | Billing | The attempt ended refused; the invoice returns to outstanding for a future legitimate proposal. | EvaluateAuthority |
| PaymentIntentIssued | Authority | A code-constructed intent exists with the exact fields that will be signed and enforced. | EvaluateAuthority |
| AuthorityDetermined | Authority | The verdict for an intent, with reason codes and the constitution version consulted at dispatch time. | EvaluateAuthority |
| PaymentAllowed | Authority | The only event that can authorize dispatch; Settlement refuses to move without it. | EvaluateAuthority |
| PaymentRefused | Authority | A refusal with its reason: digest mismatch, payee quarantined or frozen, cap exceeded, duplicate invoice, invalid approval, no owner signature. | EvaluateAuthority |
| CapacityReserved | Authority | Amount held against the daily cap for a specific intent. | ReserveCapacity |
| CapacityRefused | Authority | The cap headroom check failed; the attempt is refused without reserving anything. | ReserveCapacity |
| ApprovalRequested | Authority | An escalation opened a signature request bound to one exact intent. | EscalateForSignature |
| ApprovalGranted | Authority | The owner's EIP-712 signature verified against the bound intent; the intent may now be dispatched. | SubmitOwnerSignature |
| ApprovalRejected | Authority | Signature invalid, signer not the owner, or the binding did not match; the attempt is refused with no side effect. | SubmitOwnerSignature |
| ApprovalExpired | Authority | The signature window closed before dispatch; the owner must re-sign a fresh intent. | SubmitOwnerSignature |
| CapacityCommitted | Authority | A reservation became committed spend after settled settlement. | ReconcileReservation |
| CapacityReleased | Authority | A reservation was released because settlement did not happen; the cap headroom returns. | ReconcileReservation |
| SettlementOrdered | Settlement | An allowed intent became an executable order with its nullifier and code-generated command. | DispatchPayment |
| SettlementSubmitted | Settlement | The transaction was broadcast; a tx hash now exists and the outstanding window begins. | DispatchPayment |
| SettlementConfirmed | Settlement | The receipt reached the required confirmations; this is the only event that can commit cap and close an invoice. | SettleOnce |
| SettlementReverted | Settlement | The contract rejected the transaction, typically a duplicate nullifier or a failed on-chain precondition; treated as a refusal. | SettleOnce |
| DuplicateSettlementBlocked | Settlement | The nullifier was already spent, locally or on-chain; nothing moved. | SettleOnce |
| NullifierSpent | Settlement | The invoice's once-only marker is now consumed for this mandate scope. | SettleOnce |
| ReceiptAnchored | Settlement | A settlement receipt or evidence hash was written on-chain, giving independent integrity and time. | SealEvidence |
| EnvelopeSealed | Evidence | A domain fact was wrapped, signed and appended to the audit trail. | SealEvidence |
| EnvelopeAnchored | Evidence | The envelope hash was written on-chain, fixing its integrity and time independently of the operator. | SealEvidence |
| EvidenceVerificationFailed | Evidence | A re-verification did not match the sealed envelope or its anchor, indicating tampering or corruption. | VerifyEvidence |
| OwnerRegistered | Mandate | The owner address is bound to the household and becomes the sole signature authority. | CreateMandate |
| PayerEnrolled | Mandate | The parent is enrolled as the beneficiary of the service; no signing capability is granted. | CreateMandate |
| AgentAuthorised | Mandate | A software identity is granted proposal-only authority, bounded by the current constitution version. | CreateMandate |
| CapChanged | Mandate | A new constitution version sets a different daily ceiling; in-flight reservations continue under the version they were reserved against. | PublishConstitutionVersion |
| ThresholdChanged | Mandate | A new constitution version changes the auto-pay limit, shifting which future payments must be escalated. | PublishConstitutionVersion |

---

## Ubiquitous Language

| Term | Definition | Bounded Context | Aliases/Synonyms |
|------|-----------|----------------|-----------------|
| owner | The adult child who funds the account and authors the constitution. The only party who can change rules, add payees or approve exceptions. | Mandate | operator-of-record,account holder |
| payer | The parent whose bills are being paid. Receives the service, holds no keys, signs nothing. | Mandate | beneficiary |
| agent | Software identity that may only propose payments. Holds no keys and cannot edit policy or command paths. | Mandate |  |
| mandate | The scoped, revocable grant of authority from owner to agent, pinned to one constitution version lineage and one household. | Mandate | delegation |
| constitution | The operator-owned rule set the enforcement layer checks: caps, thresholds, allowlist, signature requirements. Immutable per version, append-only lineage. | Mandate | policy,.rigorix config |
| payee | A registered biller with a verified payout address, a verified bank digest and an eligibility status. | Mandate | biller,merchant |
| bank digest | Hash over payee routing details. Replaces raw account numbers in every downstream check; a mismatch is the bank-detail-change scam signal. | Mandate | routing hash |
| quarantine | Payee-level suspension triggered automatically by a bank-digest mismatch; cleared only by an owner re-approval. | Mandate | hold |
| freeze | Owner-initiated payee suspension. Strictly stronger than quarantine and never automatic. | Mandate | block |
| cap | The maximum total USDC that may be committed plus reserved within a rolling day, summed across all payees. | Mandate | daily limit |
| threshold | The per-payment amount above which an owner signature is mandatory, regardless of payee status. | Mandate | auto-pay limit |
| invoice | A bill document presented for payment, identified by its content hash, carrying amount, due date and a presented bank digest that is never authoritative for routing. | Billing | bill,statement |
| invoice hash | Canonical content hash of an invoice. Serves as the duplicate key off-chain and the nullifier seed on-chain. | Billing | nullifier seed |
| payment attempt | The agent's structured proposal to pay one invoice. Exists only to be judged; it carries no authority and cannot dispatch itself. | Billing | proposal |
| agent proposal | When the agent submits, the only accepted shape is a payment attempt; anything else is a proposal rejection, not a negotiation. | Billing |  |
| in-flight | The invoice already has an attempt that has been dispatched or is awaiting signature; a second attempt is refused locally. | Billing | pending |
| presented bank digest | The digest of routing details as they appear on the invoice. Compared against Mandate's verified digest; mismatch means quarantine. | Billing | invoice routing details |
| split invoices | One real obligation broken into several invoices each below the threshold. Detected by the aggregate daily cap, not by per-invoice heuristics. | Billing | structuring |
| payment intent | The code-constructed, immutable description of one payment: intent id, invoice id, payee, payee address, amount, bank digest, is_new_payee, requires_owner_signature. The unit of authority and of signature binding. | Authority | intent |
| determination | The allow/deny/escalate verdict for one intent, produced at dispatch time against the in-force constitution and live payee state, with reason codes. | Authority | verdict,decision |
| reservation | An atomic hold of amount against the daily cap for one intent; committed or released exactly once after settlement resolves. | Authority | hold,capacity reservation |
| approval | An owner EIP-712 signature over an intent's exact fields; single-use, expiring, and invalid the moment the intent changes. | Authority | owner signature,sign-off |
| escalate | The verdict for a payment that is not refused but cannot proceed without the owner: new payee or above threshold. | Authority | escalation,needs signature |
| moment of consequence | The instant a precondition check is bound to the dispatch. Authority must re-read all external state here, not at plan time. | Authority | dispatch time,check point |
| committed | Spend that has been confirmed on-chain and permanently counts against the day's cap. | Authority | spent |
| release | Returning reserved capacity to the ledger because the payment provably did not happen. Never a rollback of committed spend. | Authority | unreserve |
| is_new_payee | Flag on the intent, derived from Mandate's payee status, that forces escalation regardless of amount. | Authority |  |
| requires_owner_signature | Flag on the intent that the contract also checks on-chain; the off-chain determination and the contract must agree. | Authority |  |
| settlement | The confirmed on-chain movement of USDC from the household account to a payee address under one nullifier. | Settlement | payment execution |
| settlement order | The immutable executable form of an allowed intent, carrying payee address, amount, nullifier and the code-generated command reference. | Settlement | order |
| nullifier | Derived once-only marker from the invoice hash; the on-chain anti-double-pay key. Spending it twice is impossible by construction. | Settlement | spent marker |
| receipt | The chain proof for an order: tx hash, block, confirmations, status, and the anchor written for its evidence envelope. | Settlement | chain receipt,proof |
| commit-point lock | The property that PaymentRouter, not the app, is the final gate: whatever the off-chain state, a bad payment cannot be mined. | Settlement | second lock,on-chain lock |
| confirmation | Blocks mined after the transaction's inclusion; only after the required count is the settlement final and the cap committed. | Settlement | finality |
| run_command | The Rigorix payment step: a fixed command path plus structured params generated by code from the intent. | Settlement | payment step |
| revert | On-chain rejection of a settlement, most often a duplicate nullifier or a failed signature check. Always a refusal with evidence, never a retry. | Settlement | on-chain refusal |
| anchor | The on-chain write of an envelope hash that gives tamper evidence an independent timestamp. | Settlement | anchor tx |
| evidence envelope | Signed immutable wrapper around one domain fact, containing subject ids, the fact payload, the constitution version consulted and an HMAC. | Evidence | envelope,signed envelope |
| envelope hash | Canonical hash of an envelope including its HMAC; what gets anchored on-chain and re-compared at verification. | Evidence | sealed hash |
| anchor | The on-chain record of an envelope hash, giving independent integrity and time that the operator cannot rewrite. | Evidence | on-chain anchor |
| refusal record | A first-class evidence artifact for a denied payment, carrying the reason code and the constitution version that produced it. | Evidence | denial evidence |
| tamper evidence | HMAC proves no one in the operator domain edited the record; the anchor proves the record existed at a point in chain time. | Evidence | integrity,audit trail |
| party | One of the three roles in the mandate — owner, payer or agent — each with a fixed capability set. Roles never overlap for the MVP. | Mandate | participant |
| in force | The single constitution version currently binding on every determination. Authority must re-read it at dispatch, never cache it. | Mandate | current version,active policy |
| superseded | State of a constitution version that has been replaced. It stays queryable so past determinations can be explained against the rules they actually used. | Mandate | historical version |
| eligibility | The derived judgement of whether a payee may be paid right now: eligible, new (escalate), quarantined (refuse) or frozen (refuse). | Mandate | payability |
| verified digest | The bank digest the owner personally approved for a payee. Distinct from the digest an invoice presents, and the only one Settlement may route to. | Mandate | baseline digest,trusted digest |
| re-approval | The owner-signed act of accepting a new bank digest for a payee and lifting quarantine. | Mandate | digest re-approval |

---

## Use Cases (Application Services)

| Use Case | Context | Description | Commands / Collaborators |
|-----------|---------|-------------|---------------------------|
| CreateMandate | Mandate | Owner establishes the household mandate: registers owner address, payer, agent identity and the first constitution version. | register owner and payer,register agent identity,publish constitution version 1,scope mandate to household |
| PublishConstitutionVersion | Mandate | Owner appends a new immutable constitution version with caps, thresholds and approval rules; the previous version is superseded but retained. | validate owner authority,compute version hash,append version,mark previous superseded |
| RegisterPayee | Mandate | Owner registers a payee with a verified payout address and bank digest, establishing the trusted routing baseline. | compute bank digest,record verified address,mark payee as new,request owner signature |
| QuarantinePayee | Mandate | Reacts to a bank-digest mismatch by suspending the payee until the owner re-approves the new routing details. | compare presented digest to verified digest,set payee quarantined,invalidate pending intents for payee,notify owner |
| FreezePayee | Mandate | Owner freezes a payee so it becomes ineligible at the next dispatch even if it was eligible when the payment was planned. | verify owner authority,set payee frozen,emit PayeeFrozen |
| RecordInvoice | Billing | Registers an invoice with amount, due date, invoice hash and the bank digest as presented, without trusting it for routing. | hash invoice,attach payee reference,capture presented bank digest,detect duplicate invoice hash |
| ProposePayment | Billing | Translates an agent proposal into a structured payment attempt, rejecting any agent-supplied routing or policy field. | validate proposal shape,strip agent-supplied params,check invoice not already settled or in flight,create payment attempt |
| EvaluateAuthority | Authority | The core decision: builds a payment intent from the attempt, re-reads the in-force constitution and live payee state, and issues allow, deny or escalate with reasons. | re-read constitution version,re-read payee eligibility,check payee allowlist and digest match,check amount against threshold and caps,reserve atomically,issue determination |
| ReserveCapacity | Authority | Atomically reserves amount against the daily cap so committed plus reserved never exceeds it; refuses rather than over-books. | read committed and reserved,test cap headroom,reserve or refuse,emit CapacityReserved or CapacityRefused |
| EscalateForSignature | Authority | Converts an escalate determination into a signature request bound to the exact intent id, amount, address and bank digest. | build EIP-712 payload,bind to intent id,open approval request,publish to owner inbox |
| SubmitOwnerSignature | Authority | Verifies the owner's EIP-712 signature against the exact bound intent and either authorises dispatch or refuses without side effect. | recover signer from typed data,compare bindings,consume approval once,mark intent approved or refuse |
| ReconcileReservation | Authority | Commits or releases a reservation according to the settlement outcome so the cap ledger matches the chain. | read settlement outcome,commit reservation,or release reservation,emit ledger event |
| DispatchPayment | Settlement | Executes the allow-determined order through Rigorix run_command with a code-generated command path, then submits the PaymentRouter transaction. | verify allow determination exists,generate run_command params in code,execute via rigorix client,submit transaction,capture chain receipt |
| SettleOnce | Settlement | Enforces exactly-once settlement by deriving the invoice nullifier, rejecting local duplicates and relying on the contract revert as the final lock. | derive nullifier from invoice hash,check nullifier not spent,record nullifier on success,handle contract revert as refusal |
| SealEvidence | Evidence | Wraps every attempt, determination, refusal, approval and settlement into a signed HMAC envelope and anchors its hash on-chain. | assemble envelope,sign with HMAC,anchor envelope hash,append to audit log |
| VerifyEvidence | Evidence | Re-verifies an envelope for an auditor or the console and detects any single-byte tampering or anchor mismatch. | recompute HMAC,compare on-chain anchor,report verified or tampered |
| ProjectApprovalInbox | Console | Read-model projection for the owner of pending signature requests with exact intent details; carries no business rules. | read pending approvals,render exact intent fields |
| ReapprovePayeeDigest | Mandate | Owner signs off on the new bank details; the verified digest baseline is replaced and the payee returns to eligible. | verify owner signature on new digest,replace verified digest,set payee eligible,emit PayeeReapproved |
| ProjectPayerBills | Console | Read-only projection for the payer of handled and settled bills in household language, with the simulated bank payout labeled. | read settled and handled invoices,translate status to plain language,label simulated payout |

---

## Open Questions

Resolved by modeling: quarantine is payee-level but the baseline digest only changes via owner re-approval (PayeeReapproved); an approval is single-use and expiring, so a transient refusal requires a fresh signature; the nullifier is derived from the invoice hash and enforced by the contract, with Settlement reconciling from receipts. Still open: (1) does a revert release the reservation immediately or after a reconciliation sweep? (2) is the simulated bank payout a Settlement concern or a Console label only? (3) does Evidence own the HMAC key or receive it from operator config at boot? (4) how many confirmations does the demo claim on Sepolia before calling a receipt final?

---

## Aggregate Roots

Household, Constitution, Payee, Invoice, PaymentIntent, Determination, CapLedger, SettlementOrder, EvidenceEnvelope

---

## Analyst decision — 24-hour MVP scope (authoritative for scaffold)

**Verdict:** the six context boundaries are approved. The tactical model is enterprise-scoped and
must be pruned before scaffold. Do **not** generate code for every entity, event, FR or NFR below.
Scaffold the must-set only; mark the rest `deferred` in the module docs.

### Implement now (must)

| Context | Implement | Collapse into fields / enums / value objects |
|---|---|---|
| Mandate | Household (one seeded row), ConstitutionVersion, Payee | Owner, Payer, Agent, PartyRef → fields/VOs; Cap, Threshold → fields on ConstitutionVersion; **add `per_payee_cap_usdc`** (missing from the model) |
| Billing | Invoice, PaymentAttempt | InvoiceLine, InvoiceHash → field; BilledAmount → Money VO; AttemptStatus → enum |
| Authority | PaymentIntent, Determination, DailyCapacity (with reservation rows) | CapLedger → DailyCapacity; OwnerSignature, Approval → one Approval record; DeterminationVerdict → enum |
| Settlement | SettlementRecord (merge order + receipt), Nullifier mapping | SettlementOrder aggregate, ChainReceipt, ChainNetwork, PayeeAddress, SettlementStatus → fields/VOs/enums |
| Evidence | EvidenceEnvelope, Anchor | EnvelopeHash, VerificationResult → field/enum |
| Console | read models only | no business rules |

### Must FRs

FR-001, FR-002 (simplified: one immutable version at a time), FR-004, FR-005, FR-006, FR-007,
FR-008, FR-009, FR-010, FR-011, FR-012, FR-013, FR-014, FR-015, FR-016, FR-018, FR-019, FR-020,
FR-021, FR-022 (corrected below), FR-024.

### Should

FR-017 (commit/release), FR-023 (one anchor per demo scene, not per envelope), FR-025 (payer view),
payee re-approval, per-payee cap.

### Stretch / deferred

Quarantine recovery UX, payer read-only view, batched anchoring, capacity-ledger race,
effect-commitment Ambiguous scene, passkey.

### Corrections to the model (apply before scaffold)

1. **Evidence coverage is not 100%.** Rigorix writes a signed envelope only when an execution
   starts. A plan-time sequence denial returns a JSON-RPC error and produces **no envelope**.
   Therefore:
   - runtime precondition refusals (the poisoned invoice, the frozen payee) are the signed
     evidence scenes;
   - the plan-time `bank-change → pay` composition denial is recorded by the console with the
     rule id and explicitly labeled "policy refusal (no engine envelope)".
   Do not claim every refusal is enveloped.
2. **FR-003 wording.** The owner changes policy through the console. The restriction is that the
   agent and any unauthenticated console path cannot. Reword "agent or console" to "agent or
   unauthenticated caller"; the owner is the console's principal.
3. **Operator claim.** The operator key cannot exceed the **on-chain backstop** (allowlist,
   caps, nullifier, threshold signature). The full constitution (quarantine, bank-change rules)
   is enforced by Rigorix + Authority, not by the contract. Do not say the contract enforces the
   whole constitution.
4. **Per-payee cap.** The constitution must carry a daily cap and a per-payee cap. The exploration
   only has the daily cap. Add it to `ConstitutionVersion` and to the determination.
5. **Bank-change refusal timing.** Use a dispatch-time precondition for the signed-evidence scene.
   Keep the plan-time sequence rule as the separate composition scene. This gives both stories
   without conflating what the envelope proves.
6. **Anchor scope.** One anchor per demo scene, or a batch root. Per-envelope anchoring is too
   slow and expensive for 24 hours.
7. **Simulated bank payout.** Not a domain concept. It is a Console label (or drop it).
8. **HMAC key ownership.** Owned by Rigorix/operator config. Evidence consumes envelopes. The
   console holds a demo key only for the browser Verify button; it is not an Evidence aggregate.

### Resolved open questions

1. A revert releases the reservation immediately in the settlement callback; a reconciliation
   sweep (60 s) catches lost outcomes.
2. The simulated bank payout is a Console label, not a Settlement concept.
3. The HMAC key is operator/Rigorix config; Evidence reads envelopes, it does not own the key.
4. Confirmations: 1 on Anvil, 2 on Base Sepolia for the demo.

### Scenario traceability (the scaffold must satisfy all seven)

| # | Scenario | Contexts | Use cases | Evidence |
|---|---|---|---|---|
| 1 | Normal bill auto-pays | Billing, Authority, Settlement, Evidence | ProposePayment, EvaluateAuthority, DispatchPayment, SettleOnce, SealEvidence | Runtime envelope + USDC receipt |
| 2 | Poisoned invoice (bank changed) | Mandate, Billing, Authority | RecordInvoice, EvaluateAuthority (digest mismatch) | Dispatch precondition refusal envelope; no tx |
| 3 | Approved, then payee frozen | Mandate, Authority | FreezePayee, EvaluateAuthority (re-read) | Dispatch refusal envelope; no tx |
| 4 | Six split invoices | Billing, Authority | ProposePayment ×6, ReserveCapacity | Allowed envelopes + one cap refusal envelope |
| 5 | New payee / large amount | Mandate, Authority, Settlement | EvaluateAuthority (escalate), EscalateForSignature, SubmitOwnerSignature, DispatchPayment | Envelope + EIP-712 signature + tx |
| 6 | Duplicate bypasses the app | Settlement | SettleOnce (contract nullifier) | Contract revert + tx |
| 7 | Evidence tamper | Evidence | SealEvidence, VerifyEvidence | Browser verify OK, flip byte fails, anchor |

### Scaffold instruction

Scaffold the six contexts and the must-set records above. Mark deferred entities as `deferred`
in the module docs, not as code. The frontend API/ABI/UI contract is **outside** `.pi`:
`docs/BURSAR-BUILD-CONTRACT.md`. The domain model does not own the frontend.