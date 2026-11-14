# Evidence — Contract Freeze (Phase A)

**Module:** Evidence (supporting subdomain, service depth)
**Status:** Implemented — 2026-11-14 (frozen 2026-11-13)
**Canonical module doc:** [`.pi/architecture/modules/evidence.md`](../../.pi/architecture/modules/evidence.md)
**Depends on:** Authority (frozen) · Billing (frozen) · Mandate (implemented)
**Runtime partners (Phase B adapters):** Settlement (anchor write), Authority/Billing/Mandate event feeds
**Decisions:** [ADR-002](../../.pi/architecture/decisions/ADR-002-data-storage-strategy.md),
[ADR-003](../../.pi/architecture/decisions/ADR-003-cross-context-communication.md),
[ADR-005](../../.pi/architecture/decisions/ADR-005-authentication-authorization.md),
[ADR-006](../../.pi/architecture/decisions/ADR-006-cost-tracking-usage-metering.md),
[ADR-007](../../.pi/architecture/decisions/ADR-007-compliance-engine-architecture.md)

---

## 1. What is frozen, and what is not

Frozen: **signatures, types, the invariant ids, the refusal vocabulary, the repository/port shapes,
the three Evidence event payloads, and the HTTP contract.** Phase B filled every body without
changing a signature: `EnvelopeHash`/`EvidenceEnvelope` (canonical bytes + HMAC), the append-only
SQLAlchemy stores (`003_evidence`), `SealEvidence`/`VerifyEvidence`/`WitnessReport`, the local
anchor gateway/policy, the console-facing router and the event subscriber. The 19 behaviour suites
and the integration suites (real schema + HTTP) are green; `check_evidence_contracts.sh` proves the
interfaces still have implementations.

Not frozen (Phase B): behaviour bodies, SQLAlchemy models, migration `005_evidence`, the HMAC signer
adapter, the Settlement anchor client, the event subscriber wiring, the router/Pydantic schemas, and
the outbox writer. Phase A deliberately ships **no adapter**: a freeze that also writes persistence
hides which guarantees are still missing.

**Eleven invariants. A test that does not defend one of them does not belong in this suite.**

| Id | Invariant (rule) | Illegal state prevented | Defending suite |
|---|---|---|---|
| **E-1** | Canonical encoding is **byte-deterministic** across runs and key orderings. | A re-serialised payload looking like tampering; the same fact hashing differently on replay. | `canonical-bytes/`, `value-objects/` |
| **E-2** | Every delivered event produces **exactly one envelope with a valid HMAC**. | A fact with no witness, or two proofs for one fact. | `hmac-sealing/`, `evidenceenvelope/` |
| **E-3** | A denied payment is sealed as `PaymentRefused` **carrying its reason codes**. | A refusal that cannot be explained to the console or asserted by an auditor (scenarios 2/3/4). | `refusal-sealed/` |
| **E-4** | The same `event_id` delivered **3× produces 1 envelope**. | At-least-once delivery creating duplicate proofs and double-anchoring the same fact. | `idempotency/`, `persistence-contract/` |
| **E-5** | Envelopes are **append-only**; a correction is a new envelope linked by `previous_hash`. | Rewriting a row while the old hash stays anchored — the tampering the chain exists to expose. | `append-only/`, `persistence-contract/` |
| **E-6** | An untouched envelope verifies as **`VERIFIED` with its anchor tx**. | A verifier that cannot confirm a proof it just produced (scenario 7 positive). | `verify-ok/` |
| **E-7** | One changed payload byte raises **`HMAC_MISMATCH` naming the field**; the anchor is unchanged. | Silent local tampering, or a bare boolean that tells the console nothing (scenario 7 negative). | `one-flipped-byte/` |
| **E-8** | An envelope pointed at a different anchor hash raises **`ANCHOR_MISMATCH`**. | A locally valid forgery borrowing somebody else's on-chain proof. | `anchor-mismatch/` |
| **E-9** | The HMAC key appears in **no payload, canonical bytes, log line or DB column**. | Key recovery from stored evidence; the operator secret becoming witness data (ADR-005). | `key-isolation/` |
| **E-10** | Stopping Evidence **does not block dispatch**; the missing witness is detectable afterwards. | A witness that becomes a guard: an evidence outage stopping payments. | `witness-only/`, `ports/` |
| **E-11** | **`src/evidence/domain/` imports no FastAPI, SQLAlchemy or web3.** | A domain that cannot be tested without a web framework, an ORM or a chain client. | `layer-purity/` |

---

## 2. Frozen signatures — `src/evidence/`

### 2.1 Identifiers and values — `domain/ids.py`, `domain/values.py`

```python
EnvelopeId = NewType("EnvelopeId", str)
AnchorId   = NewType("AnchorId", str)
EventId    = NewType("EventId", str)
def new_id() -> str: ...                       # uuid4 hex — the one non-stub exception

@dataclass(frozen=True, slots=True)
class EnvelopeHash(ValueObject):
    value: str
    @classmethod
    def compute(cls, canonical_bytes: bytes, hmac: str) -> EnvelopeHash: ...   # E-1

class VerificationResult(StrEnum):
    VERIFIED | HMAC_MISMATCH | ANCHOR_MISMATCH | UNANCHORED

@dataclass(frozen=True, slots=True)
class Verification(ValueObject):
    result: VerificationResult
    failing_field: str | None = None
    anchor_tx: str | None = None
```

* `EnvelopeHash` is a value object: two equal hashes are the same proof. It is what the chain anchors
  and what verification re-compares.
* `VerificationResult` is a **closed set**. `HMAC_MISMATCH` and `ANCHOR_MISMATCH` name different
  tampering; `UNANCHORED` is not tampering — it is an envelope whose anchor is still pending.
* `Verification` is the success record returned by `verify`; the two failure outcomes are raised as
  refusals (`HmacMismatch`, `AnchorMismatch`) so callers handle the vocabulary, not a boolean.

### 2.2 `EvidenceEnvelope` — `domain/evidence_envelope.py`

```python
@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    id: EnvelopeId
    event_type: str
    subject_intent_id: str | None
    subject_invoice_id: str | None
    subject_payee_id: str | None
    payload: Mapping[str, Any]
    constitution_version: str | None
    actor: str
    occurred_at: datetime
    hmac: str
    previous_hash: str | None          # chain link, never a rewrite
    anchor_mode: str                   # per_envelope | batched | demo_only

    @classmethod
    def from_event(cls, event, *, signer, actor, previous_hash=None,
                   anchor_mode="per_envelope") -> EvidenceEnvelope: ...      # E-2, E-3, E-9
    def canonical_bytes(self) -> bytes: ...                                 # E-1
    def hash(self) -> EnvelopeHash: ...                                     # E-1
    def hmac_is_valid(self, signer) -> bool: ...                            # E-2, E-7
    def verify(self, signer, anchor) -> Verification: ...                   # E-6 … E-8
    def corrected(self, event, *, signer, actor, anchor_mode="per_envelope") -> EvidenceEnvelope: ...  # E-5
```

* Subjects and `constitution_version` are read from the event payload; a missing one stays `None`
  rather than an empty string, so "not applicable" and "empty" are distinguishable on the wire.
* `canonical_bytes` covers the fact and its chain link but **not** the id or the HMAC: a replay with a
  fresh id must not change the sealed bytes of an identical fact.
* `from_event` is the only seal path. It receives a `DomainEvent` and a signer, never a key, so E-9
  is structural: there is nowhere to put the secret.
* `corrected` appends; it never mutates. The original id and chain link are untouched and the new
  envelope's `previous_hash` is the original's hash.

### 2.3 `Anchor` — `domain/anchor.py`

```python
@dataclass(frozen=True, slots=True)
class Anchor:
    id: AnchorId
    envelope_hash: EnvelopeHash
    anchor_tx: str
    block_number: int
    chain_id: int
    anchored_at: datetime
    def matches(self, envelope_hash: EnvelopeHash) -> bool: ...              # E-8
```

An anchor is an **entity** because its identity persists; it is kept as captured, not promoted to an
aggregate. `matches` is deliberately narrow: accepting an anchor for another hash would let a tampered
row borrow a valid on-chain proof. `UNIQUE(envelope_hash)` in `evidence_anchors` is the storage mirror.

### 2.4 Refusal vocabulary — `domain/errors.py`

```python
class EvidenceRefusal(RefusalError)              # base; ADR-004 envelope, HTTP 409
class HmacMismatch(EvidenceRefusal)              # E-7; details: result, field, anchor_tx
class AnchorMismatch(EvidenceRefusal)            # E-8; details: result, expected/actual hashes
class AppendOnlyViolation(EvidenceRefusal)       # E-5; details: envelope_id
class EnvelopeNotFound(NotFoundError)            # E-6; HTTP 404

class SigningUnavailable(BursarError)            # E-10; HTTP 503, retryable
class AnchoringUnavailable(BursarError)          # E-10; HTTP 503, retryable
```

All refusals extend the shared `RefusalError`, so the API layer needs **no Evidence-specific
exception handling**: a verification failure is a documented `409` with a domain code everywhere.

| Refusal | Status | Why |
|---|---|---|
| `HmacMismatch` | `409` | The bytes no longer match their HMAC — a state conflict with the seal (E-7). |
| `AnchorMismatch` | `409` | The anchor belongs to a different hash (E-8). |
| `AppendOnlyViolation` | `409` | The caller asked to rewrite a sealed fact (E-5). |
| `EnvelopeNotFound` | `404` | Verification was asked for an id that is not on file. |
| `SigningUnavailable` | `503` | Operational, not a refusal; the fact is published and a gap is recorded (E-10). |
| `AnchoringUnavailable` | `503` | Same: never a payment failure, always a visible `UNANCHORED` gap (E-10). |

`HmacMismatch.details["field"]` names the top-level sealed field (`payload` for a DB edit). The demo may
refine it to a dotted path once the original fact is available; the frozen contract only requires a
non-empty name, so the console never renders a bare boolean.

### 2.5 Repository ports — `domain/repositories.py`

```python
class EnvelopeRepository(ABC):                    # NOT Repository[Id, Aggregate] — no save()
    async def append(self, envelope) -> None: ...                       # E-5
    async def find_by_id(self, id_) -> EvidenceEnvelope | None: ...     # E-6
    async def list_for_subject(self, *, intent_id=None, invoice_id=None,
                               payee_id=None, limit=50) -> Sequence[...]: ...  # E-5

class AnchorRepository(ABC):
    async def record(self, anchor) -> None: ...                         # E-8
    async def find_for_envelope(self, envelope_hash) -> Anchor | None: ...  # E-8

class ProcessedEventRepository(ABC):
    async def claim(self, event_id, handler) -> bool: ...               # E-4
    async def is_processed(self, event_id, handler) -> bool: ...        # E-10
```

Two rules are expressed by the signatures rather than left to convention:

1. **There is no `save`.** `EnvelopeRepository` deliberately does not extend the shared
   `Repository[Id, Aggregate]` port, because that base declares `save` — an update path. E-5 says a
   sealed envelope is never rewritten; the type system makes the update path unavailable.
2. **No transaction control.** No `commit`, `flush` or `begin`: the unit of work belongs to
   `application/` (ADR-002), which is what makes "one delivery = one atomic claim + append" checkable.

`claim` returns `True` only for the first delivery. A duplicate is normal at-least-once behaviour, not
a refusal, so the port does not raise on replay.

### 2.6 Ports — `domain/ports.py`

```python
@dataclass(frozen=True, slots=True)
class AnchorReceipt:
    anchor_tx: str
    block_number: int
    chain_id: int

@dataclass(frozen=True, slots=True)
class ExpectedEvent:
    event_id: EventId
    event_type: str
    occurred_at: datetime

class EnvelopeSigner(Protocol):
    def sign(self, canonical_bytes: bytes) -> str: ...                  # E-2, E-9
    def verify(self, canonical_bytes: bytes, hmac: str) -> bool: ...    # E-2, E-7

class AnchorGateway(Protocol):
    async def write_anchor(self, envelope_hash) -> AnchorReceipt: ...   # E-8
    async def read_anchor(self, envelope_hash) -> AnchorReceipt | None: ...  # E-6, E-8

class AnchorPolicy(Protocol):
    def mode_for(self, event_type: str) -> str: ...                     # E-2

class ExpectedEventsPort(Protocol):
    async def expected(self, *, since, until) -> Sequence[ExpectedEvent]: ...  # E-10
```

* `EnvelopeSigner` is the only thing that touches the operator-held key. A future KMS adapter swaps
  behind the same two methods; the envelope never receives the secret (E-9).
* `AnchorGateway` is the partnership ACL. Evidence never signs chain transactions: Settlement owns
  `POST /v1/anchors`, and `write_anchor` is idempotent by `envelope_hash`.
* `AnchorPolicy` records the mode (`per_envelope | batched | demo_only`, ADR-006) so a batched demo
  cannot later look individually anchored.
* `ExpectedEventsPort` is the read side of witness-only: it lets `WitnessReport` name the facts that
  should have been sealed.

None of the ports carries transaction control. Adapters live in `infrastructure/` (Phase B).

### 2.7 Application services and DTOs — `application/`

```python
@dataclass(slots=True)
class SealEvidence:                                  # FR-022
    envelopes: EnvelopeRepository
    processed: ProcessedEventRepository
    signer: EnvelopeSigner
    policy: AnchorPolicy
    anchors: AnchorGateway
    async def execute(self, command: SealEvidenceCommand) -> SealEvidenceResult: ...
        # E-2, E-4, E-10 — claim, seal, append, try anchor; never raise for a witness outage

@dataclass(slots=True)
class VerifyEvidence:                                # FR-023
    envelopes: EnvelopeRepository
    signer: EnvelopeSigner
    anchors: AnchorGateway
    async def execute(self, command: VerifyEvidenceCommand) -> VerifyEvidenceResult: ...
        # E-6 … E-8 — load, recompute, compare anchor

@dataclass(slots=True)
class WitnessReport:
    expected: ExpectedEventsPort
    processed: ProcessedEventRepository
    async def missing(self, *, since: datetime, until: datetime) -> tuple[str, ...]: ...  # E-10
```

DTOs are keyword-clear and carry no secrets:

```python
SealEvidenceCommand(event: DomainEvent, actor: str, anchor_mode: str = "per_envelope")
SealEvidenceResult(envelope_id, event_id, envelope_hash, anchor_tx=None,
                   sealed=True, duplicate=False, witness_gap=None)
VerifyEvidenceCommand(envelope_id: str)
VerifyEvidenceResult(result: VerificationResult, failing_field=None, anchor_tx=None)
EnvelopeView(...)                                    # API read model
```

`SealEvidenceResult.witness_gap` is how E-10 leaves the handler without raising: a witness that could
not do its job reports the fact, and the publisher continues. `duplicate=True` on a replay makes the
idempotency visible instead of pretending a new seal happened.

### 2.8 Domain events — `domain/events.py`

Wire names are stable and payload fields are frozen. Exactly three events exist, matching the module
doc table — no fourth (ADR-008).

| Wire name (`event_name`) | Class | Payload fields |
|---|---|---|
| `EnvelopeSealed` | `EnvelopeSealed` | `envelope_id, event_type, subject_intent_id, subject_invoice_id, subject_payee_id, envelope_hash, anchor_mode` |
| `EnvelopeAnchored` | `EnvelopeAnchored` | `envelope_id, envelope_hash, anchor_tx, block_number, chain_id` |
| `EvidenceVerificationFailed` | `EvidenceVerificationFailed` | `envelope_id, result, failing_field` |

**Consumed, not owned:** Evidence seals `PaymentRefused`, `PaymentAllowed`,
`AuthorityDetermined`, `Approval*`, `InvoiceRecorded`, `PaymentProposed`, `ProposalRejected`,
`SettlementConfirmed`, `SettlementReverted`, `DuplicateSettlementBlocked`, `PayeeQuarantined`,
`PayeeFrozen` and `PayeeReapproved`. It does **not** redeclare those classes: two definitions of one
fact drift, and the publisher owns the schema. Delivery is at-least-once, so the subscriber
deduplicates on `(event_id, handler)` (E-4).

### 2.9 HTTP contract and error envelope

Route handlers are **concrete** — `src/evidence/interfaces/http/` gets a router and Pydantic schemas
in Phase B, not a second interface file. The frozen part is the endpoint shape the console is built
against (ADR-004):

| Method | Path | Request | Success | Failure |
|---|---|---|---|---|
| `GET` | `/v1/evidence` | `?intent_id=&invoice_id=&event_type=&cursor=` | `200 EnvelopeView[]` (no payload unless `?full=1`) | `422 VALIDATION_FAILED` |
| `GET` | `/v1/evidence/{id}` | `?full=1` | `200 EnvelopeView` | `404 NOT_FOUND` |
| `GET` | `/v1/evidence/{id}/verify` | — | `200 {result: VERIFIED, anchor_tx}` | `409 {result: HMAC_MISMATCH \| ANCHOR_MISMATCH, field, anchor_tx}` |
| `GET` | `/v1/evidence/{id}/anchor` | — | `200 {anchor_tx, block_number, chain_id}` | `404 NOT_FOUND` |

The failure body is the shared ADR-004 envelope; Evidence adds no bespoke error shape:

```json
{ "error": { "code": "CONFLICT", "message": "…", "retryable": false,
             "correlation_id": "…",
             "details": { "result": "HMAC_MISMATCH", "field": "payload",
                          "anchor_tx": "0x…" } } }
```

`result` is the frozen `VerificationResult` vocabulary; `field` is never empty on a mismatch.

---

## 3. Behaviour the tests demand, in the order Phase B should implement it

1. **Canonical encoder + `EnvelopeHash`** — sorted keys, compact separators, explicit nulls; same
   content → same bytes and hash, one changed byte → different hash (E-1).
2. **`EvidenceEnvelope.from_event` + `EnvelopeSigner`** — one envelope per event, HMAC verifies, the
   key is absent from every output (E-2, E-3, E-9).
3. **Append-only store + `previous_hash` chain + `ProcessedEventRepository.claim`** — migration
   `005_evidence`; no `save`; a correction is an append (E-4, E-5).
4. **`SealEvidence`** — claim `(event_id, "seal")`, append once, try `AnchorGateway.write_anchor`;
   a signer/anchor outage becomes `witness_gap`, never a publisher error (E-2, E-4, E-10).
5. **`AnchorPolicy` + Settlement adapter** — `per_envelope` for the seven demo scenarios, `batched`
   default; `AnchorRepository.record` enforces one anchor per hash (E-8, ADR-006).
6. **`VerifyEvidence` / `EvidenceEnvelope.verify`** — HMAC first, then anchor; `HmacMismatch` names
   `payload`, `AnchorMismatch` names both hashes; untouched → `VERIFIED` with the anchor tx
   (E-6, E-7, E-8).
7. **Console-facing verification endpoint + witness-gap report** — the scenario-7 demo surface and
   the "missing witness" read model (E-10).

---

## 4. Red state — what "the tests fail for the right reason" means

Every test under `tests/unit/evidence/` asserts a **rule** and fails today because the behaviour is
`NotImplementedError`. Expected and accepted:

* `pytest.raises(HmacMismatch)` / `pytest.raises(AnchorMismatch)` around a stub raises
  `NotImplementedError` → **red**.
* A test that asserts only shape (`isinstance`, `dataclass`, `hasattr`) is **not** evidence and will be
  rejected: green assertions over `NotImplementedError` bodies prove nothing.
* As soon as a body is implemented, its test must go green **and** stay green; a test that turns green
  without a behaviour change never asserted a rule.
* The two `WitnessReport` / `SealEvidence` tests are async and drive the frozen ports with doubles, so
  they assert the idempotency and witness-only rules end-to-end rather than the stub's absence.

Verification: `bash .pi/scripts/freeze.sh verify --module evidence`
(`contracts` · `frozen signatures` · `no placeholders` · `AC references` · `red state` · `type check` · `dependencies`).

---

## 5. Explicitly out of scope for Phase A

| Not here | Why |
|---|---|
| `src/evidence/infrastructure/**` adapters (HMAC signer, SQLAlchemy models, envelope store, anchor client, migration `005_evidence`) | behaviour; Phase B. The package exists with a docstring so the DDD layer gate is satisfied; it contains no adapter. |
| `src/evidence/interfaces/http/**` (router, Pydantic schemas) | behaviour; Phase B. The endpoint shape is frozen in §2.9; app-shell registration is the runtime-integration item. |
| Settlement anchor adapter (`POST /v1/anchors`) | cross-context call; the **port** is frozen (§2.6), the adapter arrives with the persistence item. |
| Event subscriber wiring / outbox writer | needs the session factory, the unit of work and the delivery table (ADR-003). |
| `ListEnvelopes`, `GetEnvelope`, `ReanchorBatch` implementations | operational read/maintenance paths; the HTTP shape is frozen, the bodies are Phase B. |
| Key lifecycle / KMS | the key is operator config at boot and never persisted; a KMS adapter is a future implementation behind `EnvelopeSigner`. |
| Batching policy tuning for the judges | the three modes are frozen; which one a scenario uses is configuration (ADR-006), not contract. |

Rejecting these is the point of a freeze: the failing tests are the specification, and every one maps
to an invariant in §1.
