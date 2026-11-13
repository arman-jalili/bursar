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

## [2026-11-13] - Mandate: implementation complete (all 13 epic items)

### Changed
- Module: **mandate** — status Planned → Implemented; the 6 catalog application services, 7 HTTP
  endpoints and 3 repository adapters are live in `console-api`

### Added
- Domain behaviour: `BankDigest` (canonical JSON → SHA-256), `Cap`/`Threshold` guards, `Payee`
  (P-1…P-6), `Constitution` (H-4…H-8), `Household` (H-1…H-3), `PayeeEligibilityResolver`
- `InvalidValue` (also a `ValueError`), `isa`-style owner guards, `ReasonCode` wiring
- Persistence: SQLAlchemy models, mappers, adapters implementing the domain ports; optimistic
  concurrency (`StaleAggregateError`); `001_mandate` migration with the H-4 partial unique index
- Application: `services_impl.py` (one `session_scope` per use case + outbox append)
- HTTP: concrete router, scope deps (agent refused on mandate writes), owner-proof layer,
  7 endpoints, `/metrics`
- Proofing: `.pi/scripts/ci/prove_mandate_contracts.sh` (40 checks) wired as hardening stage 11 and
  as a CI job
- Observability: in-process Prometheus-text metrics with route-template labels, refusal counters,
  fail-closed trip counter
- Readiness: runbook gains Mandate procedures (quarantine, freeze, stale aggregate, outbox backlog,
  schema); DR plan gains restore-vs-chain reconciliation and RPO/RTO
- Tests: 342 total (+46 behaviour, +11 persistence, +15 HTTP end-to-end, +3 metrics)

### Deviations and corrections made while implementing
- `Payee.unfreeze` **removed**: the documented state machine has `FROZEN → [*]` only, and a transition
  with no event type would be a silent authority change. Resuming a payee is a re-registration.
- `Constitution.version()` → `find_version` (shadowed `AggregateRoot.version`, the concurrency counter).
- `Constitution.initial` gained `require_signature_for_new_payee`; `Household.change_owner` gained the
  acting owner — both because the invariant needs the input.
- Composition root restructured: `shell.build_app` is generic, each deployable's `app.py` declares
  `HOSTED_CONTEXTS`. `check_composition_root.sh` now passes for all 6 modules (it previously saw a
  split composition root as unwired).
- Schema at boot runs real Alembic migrations in a worker thread — a second schema definition
  (`metadata.create_all`) would drift from the migrations.
- `ConstitutionCorrupted`/`OwnerActionRequired` etc. build `details` as a mapping: a `**kwargs` tail
  let a payload rewrite an error's wire code.

### Impact Analysis
- Files: `src/mandate/**`, `src/apps/**`, `src/shared/**` (metrics, migrations helper, middleware),
  `migrations/**`, `tests/**`, `docs/{runbook,dr-plan}.md`, `.pi/scripts/ci/**`, `.github/workflows/ci.yml`
- Validators: ruff + mypy clean; `validate-architecture`, `check_model_judgment`,
  `check_language_consistency`, `validate-canonical`, `check_composition_root`,
  `prove_mandate_contracts` all pass; 342 tests pass

### Known environment false positives (unchanged)
- `check_architecture_conformance.sh`: probes the system `python3` and requires every `.env.example`
  variable to be exported while also requiring `.env` to differ from `.env.example` — mutually
  unsatisfiable for a demo config whose values are meant to work as-is.

### Status
- [x] Architecture doc updated
- [x] CHANGELOG entry added
- [x] Implementation updated
- [x] Canonical refs updated
- [x] Validators run

## [2026-11-13] - Mandate: Contract Freeze v1

### Changed
- Module: **mandate**
  - Frozen the public contract for the epic before implementation: value objects, aggregates
    (behaviour surface only), repository ports, domain-service ports, the 6 catalog application
    services and all request/result DTOs, plus the 12 domain-event payloads
  - Package layout `src/mandate/{domain,application,infrastructure,interfaces}/`; `infrastructure/`
    and `interfaces/` are declared-and-empty so the 4-layer contract holds without pre-empting the
    persistence/HTTP items

### Added
- `src/mandate/domain/`: `values.py` (`BankDigest`, `Cap`, `Threshold`, `PartyRef`, `Eligibility`,
  `RoutingDetails`, addresses/names, `PayeeStatus`, `ReasonCode`), `errors.py` (`MandateError`,
  `OwnerActionRequired` 403, `OwnerProofInvalid`, `ThresholdExceedsCap`, `ConstitutionCorrupted` 500,
  `PayeeNotEligible`, `PayeeAlreadyRegistered`), `events.py` (12 frozen payloads), `entities.py`
  (`Owner`/`Payer`/`Agent`), `household.py`, `constitution.py`, `payee.py`, `repositories.py`
  (3 ABCs), `ports.py` (`OwnerSignatureProof` Protocol, `EligibilityResolver` ABC), `ids.py`
- `src/mandate/application/`: `dto.py` (13 frozen DTOs), `services.py` (6 catalog ABCs +
  `EligibilityReader`)
- `tests/unit/mandate/`: 9 contract test files (~200 assertions) — the generated ones were
  uncollectable (hyphenated method names, `SyntaxError`) and tautological (`assert False`), so they
  were rewritten as shape assertions per `.pi/skills/tdd-practice.md`
- `Frozen Contracts (v1)` section in `.pi/architecture/modules/mandate.md` — types, fields, ports,
  services, reason-code ↔ wire-code table, and the three defects the freeze caught

### Defects caught by the freeze (before anything depended on them)
1. `OwnerActionRequired` silently lost its `role` detail: `ForbiddenError.__init__` chained into
   `MandateError.__init__` through the MRO of a two-parent error, nesting `details` one level deep.
2. `**details` on `MandateError` allowed `details={"code": …}` to rewrite an error's wire code.
3. `Constitution.version()` shadowed `AggregateRoot.version` (the optimistic-concurrency counter);
   renamed `find_version`, symmetrical with `ConstitutionRepository.find_version`.

### Impact Analysis
- Files affected: `src/mandate/**`, `tests/unit/mandate/**`, `pyproject.toml` (ruff/mypy scope),
  `.pi/architecture/modules/mandate.md`, `.pi/architecture/CHANGELOG.md`
- Canonical refs: every new file carries a `Canonical:` header; `validate-canonical.sh` passes
- Validators: `validate-architecture`, `check_model_judgment`, `check_language_consistency`,
  `validate-canonical` — all pass; `ruff` + `mypy` clean; 267 tests pass

### Deviations from the issue boilerplate (deliberate)
- Repository **interfaces** live in `domain/repositories.py`, not `infrastructure/repository/`: the
  issue's own body says "Repository interfaces (owned by `domain/`)", and ADR-008's
  `interface-ownership` gate requires it. Implementations go to `infrastructure/`.
- HTTP routers are **not** part of this item: the issue says controllers are concrete and get no
  contract file, and the endpoint contract is already frozen in the module doc's API table. Writing an
  empty router would be dead code (`check_composition_root.sh` exists to catch exactly that).

### Known heuristic-check noise (not defects)
- `check_ddd_structure.sh` reports `__pycache__` and `apps` as modules "missing layers". The first is
  a script artefact (no `__pycache__` filter); the second is the composition root — two deployables,
  not a bounded context. `mandate` passes all four of that script's checks.
- `check_judgment_contracts.sh` fails on harness template paths (`templates/pi/…`, `src/lib/…`,
  java skill gates) that do not exist in this repository; unrelated to this change.

### Migration Steps
1. Implementation items fill the `NotImplementedError` bodies; signatures stay as frozen.
2. Persistence item adds `mandate_*` tables (migration `001_mandate`) and the repository adapters.
3. HTTP item adds `interfaces/http/router.py` and registers it in `src/apps/shell.py`.

### Status
- [x] Architecture doc updated (Frozen Contracts v1)
- [x] CHANGELOG entry added
- [x] Implementation updated (contracts + stubs, no behaviour)
- [x] Canonical refs updated
- [x] Validators run

## [2026-11-13] - Phase 0: Project Bootstrap (implementation started)

### Changed
- Module: **all** (bootstrap only — no bounded context was built, and `src/` contains no
  `<context>/` package, per ADR-008 phase discipline)
  - Shared kernel: `Money` (integer micro-USDC, float-refusing), `ValueObject`, `AggregateRoot`
    (event recorder, kw_only, no setters), `DomainEvent` (immutable fact + delivery metadata),
    `Repository` (PEP 695 generics, no commit), `Clock` (`SystemClock`/`FrozenClock`),
    `BursarError`/`RefusalError` + closed `ErrorCode` set
  - Application layer: `unit_of_work.session_scope` — the single sanctioned transaction boundary
  - Infrastructure: `Settings` (pydantic-settings, `SecretStr`, address/decimal validators,
    `safe_dump`), JSON logging with `RedactingFilter`, SQLite engine with `journal_mode=WAL`,
    `synchronous=FULL`, `busy_timeout`, correlation-id middleware
  - Interfaces: ADR-004 error envelope, `RefusalError → 409`, `/healthz`, `/readyz`
  - Deployables: `authority-service` (:8001, no CORS) and `console-api` (:8000), both booting

### Added
- `pyproject.toml` (Python 3.12, hatchling, ruff, mypy, pytest), `uv.lock`, `.python-version`
- `Makefile` (install/test/lint/typecheck/validate/run/db/anvil/contracts/freeze-check)
- `.env.example` (24 variables, parity-tested against `Settings`), `.gitignore` (secrets + WAL files)
- `alembic.ini` + `migrations/` with `000_bootstrap` (creates no tables), two-database selector
  (`-x db=authority|console`)
- `foundry.toml` + `contracts/` scaffold (empty by design; `PaymentRouter.sol` is Phase 4)
- `.github/workflows/ci.yml`: quality (ruff/mypy/pytest), architecture gates, migrations round-trip
- `README.md`, `LICENSE` (MIT)
- 68 tests: kernel semantics, config parity + secret hygiene, log redaction, WAL pragmas,
  unit-of-work commit/rollback, both deployables booting, error envelope, CORS asymmetry

### Impact Analysis
- Files affected: new `src/`, `tests/`, toolchain and CI files as listed above
- Canonical refs: every source file carries a `Canonical:` header (validated: 25 files, 8 ADRs)
- Validators required: architecture (pass), model-judgment (pass), language-consistency (pass),
  canonical (pass)

### Known environment false positives (not defects)
- `check_architecture_conformance.sh` reports "Python 3.9 < 3.10": it probes the **system**
  `python3`, while the project targets 3.12 (`.python-version`, `requires-python >=3.12`, venv
  3.12.13, ruff/mypy/pytest all run under 3.12).
- The same script reports env collisions between `.env` and `.env.example`: the demo deliberately
  ships working Anvil values so `cp .env.example .env` runs, and `.env` is git-ignored. Faking
  differences to satisfy the check would hide nothing and prove nothing.
- `check_composition_root.sh` reports contexts "implemented but not installed": none are
  implemented yet. Deferred to the phase that builds each context (mirrored in CI and the Makefile).

### Migration Steps
1. `make install`
2. `cp .env.example .env` and rotate `BURSAR_HMAC_KEY`
3. `make test && make check && make validate`
4. Phase 1 (Mandate) creates `src/mandate/` and registers its router in
   `src/apps/shell.py:register_routers`

### Status
- [x] Architecture doc updated (roadmap Phase 0 ticked + deviations recorded)
- [x] CHANGELOG entry added
- [x] Implementation updated
- [x] Canonical refs updated
- [x] Validators run

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
| 2026-11-13 | **Phase 0 bootstrap** — kernel, config, logging, DB, envelope, 2 deployables, CI | bootstrap (no context) | complete | architecture/model-judgment/language/canonical: pass |
| 2026-11-13 | Mandate contract freeze v1 — values, aggregates, ports, DTOs, events, 9 contract tests | mandate | complete (stubs) | all four gates pass; 267 tests |

---

*Last updated: 2026-11-13*
*Framework version: 1.2.0*