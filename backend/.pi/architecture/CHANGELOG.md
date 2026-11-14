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

## [2026-11-14] - Settlement implementation: domain, persistence, read runtime

### Changed
- Module: settlement
  - Domain: `Nullifier.derive` (keccak256 via `eth-hash[pycryptodome]`), `ChainNetwork` (Anvil /
    Base Sepolia, no default), `SettlementOrder.order` / `command_params` / `mark_submitted` /
    `conclude`, `ChainReceipt` cost validation + finality, `NullifierPolicy`, `FinalityPolicy`,
    `DeterminationView.permits_dispatch`. All 80 frozen contract suites green.
  - Application: `GetReceipt`, `ListOrders`, `CostSummary`, `AnchorHash` (+ `GetOrder`,
    `ListReceipts`, `NullifierStatus` behind the frozen endpoints). `DispatchPayment`/`SettleOnce`
    remain deferred (B-1/B-2).
  - Infrastructure: SQLAlchemy models/mappers/repositories (+ outbox writer), migration
    `003_settlement` with the storage mirrors of SC-3/SC-5/SC-10.
  - Interfaces: concrete `/v1/orders*`, `/v1/receipts`, `/v1/nullifiers/{value}` router registered in
    the console-api composition root; dispatch/anchors return 501 naming the blocker.

### Impact Analysis
- Files affected:
  - `src/settlement/**` (domain bodies, application services, infrastructure adapters, HTTP router)
  - `src/apps/console_api/app.py` (settlement added to `HOSTED_CONTEXTS`)
  - `migrations/env.py`, `migrations/versions/003_settlement.py`
  - `pyproject.toml`, `uv.lock` (eth-hash[pycryptodome])
  - `tests/unit/settlement/_fixtures.py` (adds `is_anchor` to the shared receipt builder — not a frozen test file)
  - `tests/integration/settlement/**` (new persistence + HTTP E2E tests)
- Canonical refs to update:
  - `.pi/architecture/modules/settlement.md` (status → Implemented, implementation status, sequence)
  - `.pi/architecture/decisions/ADR-009-runtime-wiring-multilang-judgment.md` (new, Accepted)
  - `docs/runbook-settlement.md`, `docs/dr-plan-settlement.md` (new)
- Validators required:
  - architecture, canonical, tests, security, operations, runtime-wiring, composition-root
  - `check_settlement_contracts.sh` (new hardening stage 2c)

### Migration Steps
1. `make db-upgrade` — applies `003_settlement` (orders, nullifiers, receipts, outbox).
2. Rebuild the venv or `uv pip install -e ".[dev]"` — `eth-hash[pycryptodome]` is a new dependency.
3. Restart `console-api`; settlement routers are registered by the composition root.
4. To enable the write path, complete the re-freeze in ADR-009 (B-1, B-2) and gaps G-1…G-4.

### Status
- [x] Architecture doc updated
- [x] CHANGELOG entry added
- [x] Implementation updated (domain, persistence, read runtime)
- [x] Canonical refs updated
- [x] Validators run

## [2026-11-14] - Console: implementation complete (all 16 epic items)

### Changed
- Module: console
  - Application services (catalog): `ProjectApprovalInbox`, `ProjectPayerBills` and
    `ProjectEvidence` are implemented over the six upstream ports; the owner signature is forwarded
    byte-for-byte and Authority's refusal codes are translated to household language.
  - Anti-corruption layer: six surface whitelists (owner inbox, payer bill, payee, constitution,
    evidence, verification) with model-output refusal plus a trust-boundary scrub; byte fidelity of
    `payee_address`, `bank_digest`, `amount_usdc` and `typed_data_hash` is enforced (CON-01/CON-02).
  - Ports (upstream clients): six `httpx` adapters with a recorded upstream transport so demo/CI
    exercise the same code paths without a live Authority.
  - Interfaces: the eight frozen routes, OpenAPI response models, the ADR-005 demo scope map and a
    409 envelope for console refusals; the runtime composition root installs the context.
  - Proofing: `check_console_contracts.sh` + hardening stage 11 prove the contract on every build.
  - Operability: `docs/runbook-console.md`, `docs/dr-plan-console.md`.

### Impact Analysis
- Files affected:
  - src/console/application/**
  - src/console/infrastructure/**
  - src/console/interfaces/**
  - src/apps/console_api/app.py
  - src/apps/shell.py
  - tests/unit/console/**, tests/integration/console/**
  - pyproject.toml (httpx runtime dependency)
- Canonical refs to update:
  - .pi/architecture/modules/console.md#architecture
  - .pi/architecture/modules/console.md#anti-corruption-layer--field-whitelists
  - .pi/architecture/modules/console.md#api-endpoints

### Migration
- None. The console owns no tables; `src/console/domain/` still does not exist (CON-09 / ADR-008).

### Validation
- 62 frozen contract tests + 34 support tests + 19 integration tests pass.
- `pytest --cov=src/console --cov-fail-under=90` → 95%.
- Validators: ci, tests, security, wiring, guards, drift, shell, claims, floors, architecture,
  canonical — pass.

---

## [2026-11-15] - Settlement: two-phase `ChainGateway` (B-1 closed) and the governed broadcast step

### Changed
- Module: settlement
  - `ChainGateway`: `submit(order) -> str` replaced by `prepare(order) -> SignedPayment` and
    `broadcast(signed) -> None`. The hash now exists before anything is broadcast, so SC-3's
    write-ahead ordering is expressible at last (blocker B-1).
  - `SignedPayment` added to `domain/ports.py` (`tx_hash`, `raw_transaction`); `CommandAck` gained
    `command_text` (the rendered command the governed step executed).
  - `SettlementStatus.SIGNED` (`"signed"`) and `SettlementOrder.mark_signed(tx_hash, raw_transaction,
    signed_amount)`; `mark_submitted` now also accepts `SIGNED -> SUBMITTED`, and `raw_transaction`
    travels with the hash so a recovery re-sends the same bytes instead of signing a second nonce.
  - `Web3ChainGateway`: `_send_sync` split into `_sign_sync` (local signing, returns `SignedPayment`) and
    `_send_sync(raw)` (sends bytes); `broadcast` refuses bytes whose hash is not the recorded one, before
    the node sees them.
  - `DispatchPaymentService`: live gate → `prepare` → persist hash **and** signed bytes (`signed`) →
    governed `payments.broadcast` → `SUBMITTED`. A refused governed step leaves the order `signed` with
    its hash. Signing happens before the row is inserted, so a signing refusal persists nothing.
  - `RigorixCommandAdapter`: `DISPATCH_COMMAND` is now `payments.broadcast --raw-tx {raw_transaction}`
    (still a module constant rendered from the order, SC-2); an unsigned order is refused before the host
    is contacted.
  - New console script `payments.broadcast` (`src/settlement/infrastructure/chain/broadcast_cli.py`): one
    option, no database, no order lookup, no network re-derivation, no signer.
  - Migration `005_settlement_signed`: `settlement_orders.raw_transaction` and
    `ck_settlement_orders_status` (the closed lifecycle, now including `signed`).
- Files affected:
  - src/settlement/domain/ports.py
  - src/settlement/domain/settlement_order.py
  - src/settlement/domain/values.py
  - src/settlement/application/dispatch.py
  - src/settlement/application/dto.py
  - src/settlement/application/services.py
  - src/settlement/application/services_impl.py
  - src/settlement/infrastructure/chain/{web3_gateway,broadcast_cli,__init__}.py
  - src/settlement/infrastructure/rigorix/command_adapter.py
  - src/settlement/infrastructure/{models,mappers,repositories}.py
  - src/settlement/interfaces/http/router.py
  - migrations/versions/005_settlement_signed.py
  - pyproject.toml (`[project.scripts]`)
  - tests/unit/settlement/{chain,rigorix,write-ahead-hash}/
- Canonical refs to update:
  - docs/contracts/settlement-contract-freeze.md §2.8, §7 (the amendment)
  - .pi/architecture/modules/settlement.md#ports-infrastructure-adapters
  - .pi/architecture/modules/settlement.md#aggregate-settlementorder
  - .pi/architecture/modules/settlement.md#acceptance-criteria
  - docs/runbook-settlement.md §1, §4, §6, §7

### Impact Analysis
- B-1 is closed; **B-2 remains open** (`PENDING`/`ABANDONED` still have no intention method), so
  `SettleOnce` and finality are still unimplemented and an order stops at `submitted`.
- `ChainGateway.broadcast` has no production caller: the governed path broadcasts through Rigorix's
  `run_command`. It is the adapter-level form of the same single operation (same bytes, no new
  transaction) and is exercised by the chain suite.
- Validators required: ci, tests, security, operations, integration, architecture, canonical,
  composition-root, settlement contract proofing.

### Migration Steps
1. `make db-upgrade` (revision `005_settlement_signed`).
2. Install the console script in the Rigorix sandbox image (`pip install .`) so the governed step can run
   `payments.broadcast`.
3. Start `rigorix-server` with `RIGORIX_SANDBOX=container RIGORIX_HMAC_KEY=<key>`; keep
   `BURSAR_RIGORIX_SANDBOX=container` in the API environment.
4. Pre-existing `ordered` rows are unaffected; the new state only appears on a dispatch.

### Status
- [x] Architecture doc updated
- [x] Contract amendment recorded (`settlement-contract-freeze.md` §7)
- [x] Runbook updated with the operating procedure for a `signed` order

---

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
| 2026-11-14 | **Console implementation** — projections, ACL, ports, eight routes, mobile contract, runbook + DR plan, proofing stage 11 | console | complete | ci/tests/security/wiring/guards/drift/shell/floors/architecture/canonical: pass |
| 2026-11-13 | ADRs 001–007 accepted; diagrams + roadmap generated | all | pending (no `src/`) | not run |
| 2026-11-13 | **Phase 0 bootstrap** — kernel, config, logging, DB, envelope, 2 deployables, CI | bootstrap (no context) | complete | architecture/model-judgment/language/canonical: pass |
| 2026-11-13 | Mandate contract freeze v1 — values, aggregates, ports, DTOs, events, 9 contract tests | mandate | complete (stubs) | all four gates pass; 267 tests |
| 2026-11-14 | **Billing implementation** — value objects, aggregates (B-1…B-7), repositories, migration `002_billing`, HTTP surface, settlement/refusal handlers, contract proofing stage | billing | complete | ci/tests/security/wiring/guards/drift/shell/claims/floors: pass |
| 2026-11-14 | **Settlement implementation** — value objects, aggregate + domain services, SQL repositories + migration `003_settlement`, read API wired into console-api, ADR-009, runbook + DR plan, proofing stage 2c | settlement | complete (write path deferred on B-1/B-2) | architecture/canonical/security/operations/runtime-wiring/composition-root: pass; settlement proofing 74/74 |
| 2026-11-15 | **Settlement write path** — two-phase `ChainGateway` (`prepare`/`broadcast`), `SIGNED` state + `mark_signed`, governed `payments.broadcast` step, migration `005_settlement_signed`; B-1 closed, B-2 open | settlement | complete (B-2 open) | architecture/canonical/security/operations/integration/ci/tests: pass; settlement proofing 89/89 |

---

*Last updated: 2026-11-15*
*Framework version: 1.2.0*