# Architecture Change Log

<!--
Canonical Reference: .pi/architecture/CHANGELOG.md
Blueprint Source: Guardian Framework v1.2
DO NOT EDIT GENERATED FILES - Modify this source only
-->

This document tracks all architecture changes requiring implementation updates.

---

## Change Log Format

Each entry follows this structure:

```markdown
## [YYYY-MM-DD] - [Change Title]

### Changed
- Module: [module-name]
  - [Component]: [what changed]
  - [Component]: [what changed]

### Impact Analysis
- Files affected:
  - src/[path1]
  - src/[path2]
- Canonical refs to update:
  - .pi/architecture/modules/[module].md#[section]
- Validators required:
  - [validator-name]

### Migration Steps
1. [Step 1]
2. [Step 2]
3. [Step 3]

### Status
- [ ] Architecture doc updated
- [ ] CHANGELOG entry added
- [ ] Implementation updated
- [ ] Canonical refs updated
- [ ] Validators run
```

---

## Entries

## [2026-11-13] - Complete Architecture Package (all 6 bounded contexts)

### Changed
- Module: **mandate** (tactical / core)
  - Aggregates: `Household` (H-1…H-3), `Constitution` (H-4…H-8), `Payee` (P-1…P-6) with python stubs, behaviour methods and aggregate-local invariants mapped to `illegalStatePrevented`
  - Value objects: `BankDigest`, `Cap`, `Threshold`, `PayeeStatus`, `PartyRef` with entity-vs-VO justification
  - Domain events: 12 (all triaged) with payloads and publisher
  - Endpoints: 11 documented with scopes and signature requirements
  - Dependencies, implementation sequence (9 steps), patterns/OOP mapping, 13 acceptance criteria
- Module: **authority** (tactical / core)
  - Aggregates: `PaymentIntent` (A-1…A-4), `Determination` (A-5…A-8), `CapLedger`+`Reservation` (A-9…A-12); entities `Approval` (A-13…A-15)
  - Value objects: `Money`, `OwnerSignature`, `DeterminationVerdict`
  - Ports: `MandateView` (read-through, no cache), `AttemptViewPort` (ACL from Billing)
  - Domain events: 12 triaged with payloads
  - Endpoints: 8, including the fail-closed `POST /v1/precondition/check` (Lock 2)
  - 15 acceptance criteria including cap concurrency and signature binding
- Module: **settlement** (tactical / core)
  - Aggregate: `SettlementOrder` (S-1…S-6) with write-ahead tx hash and terminal revert
  - Value objects: `Nullifier`, `PayeeAddress`, `ChainNetwork`, `SettlementStatus`
  - Ports: `PaymentExecutor` (Rigorix), `ChainGateway` (web3), `DeterminationGate`
  - Domain events: 7 triaged with payloads; endpoints: 6
  - 12 acceptance criteria incl. both duplicate-settlement paths (scenario 6)
- Module: **billing** (service / supporting)
  - Persistence contract + service depth only: `Invoice` (B-1…B-4), `PaymentAttempt` (B-5…B-7)
  - `FORBIDDEN_PROPOSAL_KEYS` reject-not-sanitize policy
  - Domain events: 7 triaged; endpoints: 5; 8 acceptance criteria
  - No aggregates/VOs/events invented beyond the exploration capture
- Module: **evidence** (service / supporting)
  - `EvidenceEnvelope` with canonical encoding + HMAC, `EnvelopeHash`, `VerificationResult`
  - Append-only persistence contract with `previous_hash` chain and event idempotency
  - Domain events: 3 triaged; endpoints: 4; 11 acceptance criteria incl. one-flipped-byte
- Module: **console** (adapter / generic)
  - No domain layer by design; ACL whitelist projections for 3 read models
  - Plain-language copy table (owner vs payer audiences), simulated-payout labeling
  - Endpoints: 8 (one mutating, a signature passthrough); 10 acceptance criteria

### Added
- ADRs 001–007 (all Accepted): architecture pattern, storage (SQLite/SQLAlchemy, not Postgres/SQLx — language is Python), cross-context events with outbox, REST + OpenAPI `/v1`, API keys + scopes + EIP-712 consequence authorization, cost/usage metering (cap ledger as single truth + gas receipts + anchor batching), constitution enforcement engine (three locks)
- `.pi/architecture/diagrams/event-flow.md` — 34 events across 5 contexts, happy path, refusal path, triage summary
- `.pi/architecture/diagrams/system-context.md` replaced — actors, trust boundaries, deployment view, context flow
- `.pi/architecture/implementation-roadmap.md` — Phase 0 Bootstrap + 6 module phases (hours, not days), dependency graph, effort estimates, milestones, explicit must/should/stretch cut line
- Per-module diagrams: data flow, entity relationship, aggregate state, key use-case sequence (30 diagrams total)

### Impact Analysis
- Files affected:
  - `.pi/architecture/modules/{mandate,billing,authority,settlement,evidence,console}.md`
  - `.pi/architecture/decisions/ADR-00{1..7}-*.md`
  - `.pi/architecture/diagrams/{system-context,event-flow}.md`
  - `.pi/architecture/implementation-roadmap.md`
  - `.pi/architecture/CHANGELOG.md`
- Canonical refs to update:
  - `.pi/architecture/modules/*.md#components` (each stub carries a `Canonical:` header)
- Validators required:
  - architecture-validator: layer purity (no framework imports in `domain/`)
  - security-validator: HMAC key isolation, agent scope matrix, no secrets in envelopes
  - test-validator: cap concurrency, signature binding, duplicate settlement

### Corrections made during enrichment
- Scaffold said "Rust DDD + SQLx + Axum" in six module docs. Corrected to **Python / FastAPI / SQLAlchemy 2.0 / SQLite (WAL)**. Project language is `python` per `guardian-manifest.json`.
- Scaffold repeated all eight context invariants under every aggregate. Replaced with aggregate-local invariants (H-*, P-*, A-*, S-*, B-*, E-*) so each rule sits on the boundary that can actually enforce it.
- Blueprint ADR-002 prescribed Postgres + SQLx and ADR-006 prescribed SaaS usage metering. Both re-scoped honestly to this domain (SQLite; cap ledger + gas receipts + anchor batching) rather than copied.
- `.pi/architecture/diagrams/system-overview.md` left untouched (superseded by `system-context.md` + `event-flow.md`).

### Migration Steps
1. Read `implementation-roadmap.md` Phase 0 and bootstrap the project; do **not** create context folders.
2. Build phases in order (Mandate → Billing → Authority → Settlement → Evidence → Console); each phase creates its own folders and migrations.
3. Freeze the OpenAPI schema at hour 6 so the React app can proceed against mocks.
4. Add `Canonical:` headers in every implementation file pointing at its module doc section.
5. Run architecture validators after each phase, not at the end.

### Status
- [x] Architecture doc updated
- [x] CHANGELOG entry added
- [ ] Implementation updated (not started — exploration/scaffold only, per instruction)
- [x] Canonical refs updated (in doc stubs)
- [ ] Validators run (require `src/`, which does not exist yet)

<!-- Add new entries above this line -->

---

## Template Usage

When making architecture changes:

1. **Before change**: Review existing architecture docs
2. **During change**: Update `.pi/architecture/modules/[module].md`
3. **After change**: Add entry to this CHANGELOG
4. **Implementation**: Follow migration steps, update canonical refs
5. **Validation**: Run `validate-canonical.sh` to verify sync

---

## Architecture Sync Status

Track which changes have been synced to implementation:

| Date | Change | Module | Sync Status | Validator Status |
|------|--------|--------|-------------|------------------|
| 2026-11-13 | Complete architecture package — aggregates + python stubs + invariants | mandate | pending (no `src/`) | not run |
| 2026-11-13 | Complete architecture package — intent/determination/ledger + ports | authority | pending (no `src/`) | not run |
| 2026-11-13 | Complete architecture package — order/nullifier/receipt + chain adapter | settlement | pending (no `src/`) | not run |
| 2026-11-13 | Service-depth enrichment — persistence contract, proposal rejection | billing | pending (no `src/`) | not run |
| 2026-11-13 | Service-depth enrichment — envelope/HMAC/anchor, append-only store | evidence | pending (no `src/`) | not run |
| 2026-11-13 | Adapter-depth enrichment — ACL whitelists, read models, no domain layer | console | pending (no `src/`) | not run |
| 2026-11-13 | ADRs 001–007 accepted; diagrams + roadmap generated | all | pending (no `src/`) | not run |

---

*Last updated: 2026-11-13*
*Framework version: 1.2.0*