# Billing — Contract Freeze (Phase A)

**Module:** Billing (supporting subdomain, service depth)
**Status:** Frozen for implementation — 2026-11-13
**Canonical module doc:** [`.pi/architecture/modules/billing.md`](../../.pi/architecture/modules/billing.md)
**Decisions:** [ADR-001](../../.pi/architecture/decisions/ADR-001-architecture-pattern.md),
[ADR-002](../../.pi/architecture/decisions/ADR-002-data-storage-strategy.md),
[ADR-003](../../.pi/architecture/decisions/ADR-003-cross-context-communication.md)

---

## 1. What is frozen, and what is not

Frozen: **signatures, types, the refusal vocabulary with its status codes, the seven event payload
schemas, the two domain ports, and the invariant ids**. Every behaviour body is
`raise NotImplementedError("B-n — see module doc")`, so the module cannot do anything yet — by design.

Not frozen (Phase B, implementation): behaviour bodies, SQLAlchemy models, migrations, the HTTP
router, the event handlers, and the Mandate digest-review adapter. Phase A deliberately ships **no**
adapter: a contract freeze that also writes persistence is not a freeze, and it hides which
guarantees are still missing.

**The seven invariants below are the module's whole reason to exist.** A test that does not defend one
of them does not belong in the suite.

| Id | Invariant (rule) | Illegal state prevented | Defended by |
|---|---|---|---|
| **B-1** | An invoice has **at most one non-terminal payment attempt** at a time. | Two concurrent attempts racing the same invoice into a double payment. | `tests/unit/billing/at-most-one-attempt/` |
| **B-2** | An invoice whose attempt **settled is closed** and cannot spawn further attempts. | Re-paying a bill after a confirmed settlement (scenario 6). | `tests/unit/billing/settled-invoice/` |
| **B-3** | An **invoice hash identifies the bill**: a second identical hash is the same invoice. | Duplicate invoices from a replay entering the funnel as new demand. | `tests/unit/billing/duplicate-invoice/`, `tests/unit/billing/persistence-contract/` |
| **B-4** | `presented_digest` is stored **for comparison only** and never used for routing. | Invoice-supplied bank details reaching settlement (scenario 2). | `tests/unit/billing/digest-review/` |
| **B-5** | A proposal supplying a **command path, payee address, cap or threshold is rejected outright, not sanitized**. | A prompt injection smuggling parameters into `run_command`. | `tests/unit/billing/forbidden-fields/` |
| **B-6** | Amount must be **positive USDC and equal to the invoice amount**. | Splitting one bill into edited-amount attempts to dodge the threshold. | `tests/unit/billing/invoicehash/`, `tests/unit/billing/ports/` |
| **B-7** | Only an **allow or escalate** determination moves an attempt to dispatched; a refusal leaves it **terminal with no side effect**. | A refused attempt retried implicitly into a payment. | `tests/unit/billing/refusal-path/`, `tests/unit/billing/layer-purity/` |

---

## 2. Frozen signatures — `src/billing/`

### 2.1 Value objects — `domain/values.py`

```python
@dataclass(frozen=True, slots=True)
class InvoiceHash(ValueObject):
    value: str

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> InvoiceHash: ...  # B-3


@dataclass(frozen=True, slots=True)
class BilledAmount(ValueObject):
    micro_usdc: int

    @classmethod
    def from_usdc(cls, amount: str | Decimal) -> BilledAmount: ...  # B-6
```

* `InvoiceHash` is the **duplicate key off-chain and the nullifier seed on-chain** — one value, two
  jobs, because a second definition would eventually disagree.
* `BilledAmount` is integer micro-units (ADR-002). A float would let an amount pass an equality check
  against the invoice while differing by a rounding error.

### 2.2 Enumerations — `domain/values.py`

```python
class InvoiceStatus(StrEnum):
    RECEIVED | OUTSTANDING | IN_FLIGHT | SETTLED


class AttemptStatus(StrEnum):
    PROPOSED | ESCALATED | APPROVED | DISPATCHED | SETTLED | REFUSED | EXPIRED
```

Both are **closed sets with one-way transitions**: `SETTLED` and `REFUSED` are terminal. There is no
`CANCELLED`, no `REVERSED`, and no "reset" — an attempt that could un-refuse itself is B-7's failure
mode.

### 2.3 `Invoice` — `domain/invoice.py` (aggregate root)

```python
@dataclass(eq=False)
class Invoice(AggregateRoot):
    id: InvoiceId
    payee_id: PayeeId
    hash: InvoiceHash
    amount: BilledAmount
    due_date: date
    presented_digest: BankDigest
    status: InvoiceStatus

    @classmethod
    def from_document(
        cls, *, payee_id, amount, due_date, document, presented_digest, existing_hashes=()
    ) -> Invoice: ...  # B-3
    def can_accept_attempt(self) -> bool: ...  # B-1 / B-2
    def is_duplicate_of(self, other: InvoiceHash) -> bool: ...  # B-3
    def mark_settled(self) -> None: ...  # B-2
```

The factory is `from_document`, deliberately **not** `record`: `AggregateRoot.record(self, event)` is the
event recorder, and a classmethod of the same name shadowed it — `invoice.record(InvoiceRecorded(...))`
would have called the factory instead of recording a fact. Found by mypy during the Authority freeze;
amended under an unfreeze. `mark_settled` is the only transition that closes the invoice, and it refuses to run twice (`B-2`).
There is **no setter** and no `update()`, so `status` can only move through intention methods.

### 2.4 `PaymentAttempt` — `domain/payment_attempt.py` (aggregate root)

```python
FORBIDDEN_PROPOSAL_KEYS: frozenset[str] = frozenset({...})  # command, command_path, payee_address,
# cap, threshold, constitution_version,
# requires_owner_signature, is_new_payee


@dataclass(eq=False)
class PaymentAttempt(AggregateRoot):
    id: AttemptId
    invoice_id: InvoiceId
    status: AttemptStatus

    @classmethod
    def from_proposal(cls, payload: Mapping[str, object], invoice: Invoice) -> PaymentAttempt:
        ...
        # B-5, B-1, B-2, B-6

    def mark_dispatched(self) -> None: ...  # B-7
    def mark_refused(self, reason: str) -> None: ...  # B-7
```

`from_proposal` is the **only** entry point, and it is the ACL boundary: the payload is a set of
*identifiers*, and everything else the caller sends is either used to look something up or rejected.
Rejection is `raise ProposalRejected`, never "ignore the field" — silent sanitization teaches an
attacker which fields survive.

### 2.5 Refusal vocabulary — `domain/errors.py`

```python
class BillingRefusal(RefusalError)          # base; ADR-004 envelope, HTTP 409
class DuplicateInvoice(BillingRefusal)      # B-3
class InvoiceNotPayable(BillingRefusal)     # B-1
class InvoiceAlreadySettled(InvoiceNotPayable)   # B-2
class ProposalRejected(BillingRefusal)      # B-5; HTTP 422 — malformed input, not state
class AmountMismatch(BillingRefusal)        # B-6
```

All six extend the shared `RefusalError`, so the API layer needs **no Billing-specific exception
handling**: a refusal is a documented error with a domain code, everywhere in this context. The
status is part of the contract, not left to the router:

| Refusal | Status | Why |
|---|---|---|
| `DuplicateInvoice` | `409` | The bill already exists — a state conflict. |
| `InvoiceNotPayable` | `409` | An attempt is already in flight — a state conflict (B-1). |
| `InvoiceAlreadySettled` | `409` | Settlement is final — a state conflict (B-2). |
| `ProposalRejected` | `422` | Forbidden keys are malformed *input*, not state (B-5, AC #4). |
| `AmountMismatch` | `409` | The proposal conflicts with the recorded invoice amount (B-6). |

`422 PROPOSAL_REJECTED` is the one documented carve-out from ADR-004's blanket `409`: AC #4 and the
forbidden-proposal scenario both pin it, and it is the only refusal that can be decided without
looking at state at all. The carve-out lives in `ProposalRejected.__init__` so every caller — HTTP,
fixture, test — gets the same status.

### 2.6 Repository ports — `domain/repositories.py`

```python
class InvoiceRepository(Repository[InvoiceId, Invoice], ABC):
    async def add(self, invoice: Invoice) -> None: ...  # raises DuplicateInvoice (B-3)
    async def find_by_id(self, id_: InvoiceId) -> Invoice | None: ...
    async def find_by_hash(self, hash_: InvoiceHash) -> Invoice | None: ...  # B-3 lookup
    async def save(self, invoice: Invoice) -> None: ...


class PaymentAttemptRepository(Repository[AttemptId, PaymentAttempt], ABC):
    async def add(self, attempt: PaymentAttempt) -> None: ...  # raises InvoiceNotPayable (B-1)
    async def find_by_id(self, id_: AttemptId) -> PaymentAttempt | None: ...
    async def find_active_for_invoice(
        self, invoice_id: InvoiceId
    ) -> PaymentAttempt | None: ...  # B-1
```

Ports are **owned by `domain/`** and declare **no transaction control** (`commit`, `flush`, `begin`) —
the unit of work belongs to the application layer (ADR-002, `txn-placement` gate). `find_active_for_
invoice` exists so B-1 has one obvious call site instead of a scatter of `WHERE status NOT IN (...)`
predicates.

### 2.7 Application services — `application/services.py`

```python
class RecordInvoice(ABC):
    async def execute(self, command: RecordInvoiceCommand) -> RecordInvoiceResult: ...  # B-3, B-4


class ProposePayment(ABC):
    async def execute(
        self, command: ProposePaymentCommand
    ) -> ProposePaymentResult: ...  # B-5, B-1, B-2, B-6
```

Names are fixed by the exploration use-cases pass (`FR-007`, `FR-009`). One application service = one
transaction = one outbox append; both write `billing_outbox` in the same transaction as the state
(ADR-003).

### 2.8 Domain events — `domain/events.py`

Wire names are stable (they are sealed into evidence envelopes and keyed by subscribers); payload
fields are frozen. Exactly seven events exist, matching the module doc table — no eighth.

| Wire name (`event_name`) | Class | Payload fields |
|---|---|---|
| `InvoiceRecorded` | `InvoiceRecorded` | `invoice_id, payee_id, invoice_hash, amount_micro_usdc, due_date_iso, presented_digest` |
| `DuplicateInvoiceDetected` | `DuplicateInvoiceDetected` | `invoice_id, invoice_hash, original_invoice_id` |
| `PaymentProposed` | `PaymentProposed` | `attempt_id, invoice_id, payee_id, amount_micro_usdc` |
| `ProposalRejected` | `ProposalRejectedEvent` | `attempt_id, offending_fields: tuple[str, ...], reason` |
| `AttemptDispatched` | `AttemptDispatched` | `attempt_id, invoice_id, intent_id` |
| `InvoiceSettled` | `InvoiceSettled` | `invoice_id, invoice_hash, tx_hash` |
| `AttemptRefused` | `AttemptRefused` | `attempt_id, invoice_id, reason_codes: tuple[str, ...]` |

* **`ProposalRejectedEvent`**, not `ProposalRejected`: `domain/errors.py` already owns that name for
the refusal. The **wire name stays `ProposalRejected`** — subscribers and evidence key on it.
* Amounts are `amount_micro_usdc` (ADR-002). A float or a decimal string on the wire would let a
replayed event disagree with the stored amount.
* **No routing fields, ever.** `presented_digest` is a digest, `payee_id` is Mandate's reference;
a raw account number or address on the wire would defeat the ACL (B-4).

**Consumed, not owned:** Billing consumes `SettlementConfirmed` (owned by Settlement) to run
`InvoiceSettled`. The inbound contract Billing requires is `event_id`, `invoice_id`, `tx_hash`, and
delivery is at-least-once, so the subscriber deduplicates on `(event_id, handler)` (ADR-003). Billing
does **not** declare a second `SettlementConfirmed` class — two definitions of one fact drift, and
the publisher owns the schema.

### 2.9 Domain ports — `domain/ports.py`

```python
@dataclass(frozen=True, slots=True)
class DigestReview:
    payee_id: str
    matches: bool
    quarantined: bool
    verified_digest: str = ""
    status: str = ""


class DigestReviewPort(Protocol):
    async def review(
        self, *, invoice_id: str, payee_id: str, presented_digest: BankDigest
    ) -> DigestReview: ...  # B-4


class InvoiceDocumentParser(Protocol):
    def parse(self, raw: bytes) -> Mapping[str, object]: ...  # B-3
```

* `DigestReviewPort` is the Mandate anti-corruption boundary. It returns a **view**, never a policy:
Billing may store the fact, but cannot route on it (B-4). A mismatch is reported, **not raised** — the
poisoned invoice must still be recorded so the mismatch becomes evidence (scenario 2).
* `InvoiceDocumentParser` is the only thing that turns a raw document into the normalized mapping
hashed by `InvoiceHash` (B-3). Fixture-backed in the hackathon; PDF/OCR is a stretch item.
* Ports are `Protocol`s, not `ABC`s, and carry **no transaction control** — the unit of work belongs
to `application/` (ADR-002). The adapters (`MandateHttpAdapter`, fixture loader) are Phase B and live
in `infrastructure/`.

### 2.10 HTTP contract and error envelope

Route handlers are **concrete** — `src/billing/interfaces/http/` gets a router and Pydantic schemas,
not a second interface file. The frozen part is the endpoint shape, which the console is built
against (ADR-004, NFR-006):

| Method | Path | Request | Success | Refusals |
|---|---|---|---|---|
| `POST` | `/v1/invoices` | `payee_id, amount_micro_usdc, due_date, document, presented_digest` | `201 InvoiceView` | `409 DUPLICATE_INVOICE`, `422 VALIDATION_FAILED` |
| `GET` | `/v1/invoices` | `?status=&cursor=&limit=` | `200 InvoiceView[]` | — |
| `GET` | `/v1/invoices/{id}` | — | `200 InvoiceView` | `404 NOT_FOUND` |
| `POST` | `/v1/attempts` | `invoice_id`, optional `proposed_amount_micro_usdc` — **nothing else** | `201 AttemptView` | `422 PROPOSAL_REJECTED`, `409 INVOICE_NOT_PAYABLE`, `409 AMOUNT_MISMATCH` |
| `GET` | `/v1/attempts/{id}` | — | `200 AttemptView` | `404 NOT_FOUND` |

`POST /v1/attempts` accepts an optional `proposed_amount_micro_usdc` **only** so B-6 is reachable
over the wire: if present it must equal the invoice amount, otherwise `409 AMOUNT_MISMATCH`. Every
other field (`payee_address`, `command`, `cap`, `threshold`, …) is rejected with `422
PROPOSAL_REJECTED`, never ignored (B-5). `POST` endpoints accept `Idempotency-Key` (ADR-004).

Every failure uses the shared envelope — Billing adds no bespoke error body:

```json
{ "error": { "code": "PROPOSAL_REJECTED", "message": "…",
             "retryable": false, "correlation_id": "…",
             "details": { "offending_fields": "command,payee_address" } } }
```

`code` is the closed `ErrorCode` set (`DUPLICATE_INVOICE`, `PROPOSAL_REJECTED`, `AMOUNT_MISMATCH`,
`CONFLICT`, `VALIDATION_FAILED`, …), and `details` carries ids/field names only — never amounts the
caller did not send and never routing data.

---

## 3. Behaviour the tests demand, in the order Phase B should implement it

1. `InvoiceHash.from_document` — canonical content hash; identical documents equal, one changed
   character different (B-3).
2. `BilledAmount.from_usdc` — positive, exact 6-decimal parsing, float input refused (B-6).
3. `Invoice.from_document` — duplicate hash raises `DuplicateInvoice`; presented digest stored verbatim and
   never used for routing (B-3, B-4).
4. `Invoice.can_accept_attempt` / `mark_settled` — one attempt at a time, settled is terminal
   (B-1, B-2).
5. `PaymentAttempt.from_proposal` — forbidden key → `ProposalRejected`; pending attempt → 
   `InvoiceNotPayable`; settled invoice → `InvoiceAlreadySettled`; amount ≠ invoice → `AmountMismatch`
   (B-5, B-1, B-2, B-6).
6. `mark_dispatched` / `mark_refused` — a refusal is terminal and produces no dispatch (B-7).
7. Ports + adapters + migration — the storage mirrors of B-1 and B-3 (unique hash, partial unique
   index on the active attempt), then `RecordInvoice` / `ProposePayment` wiring, then the HTTP router.

---

## 4. Red state — what "the tests fail for the right reason" means

Every test file under `tests/unit/billing/` asserts a **rule** and fails today because the behaviour
above is `NotImplementedError`. Expected and accepted:

* `pytest.raises(<BillingRefusal subclass>)` around a stub raises `NotImplementedError` → **red**.
* A test that asserts only shape (`isinstance`, `dataclass`, `hasattr`) is **not** evidence and will be
  rejected: green assertions over `NotImplementedError` bodies prove nothing.
* As soon as a body is implemented, its test must go green **and** stay green; a test that turns green
  without a behaviour change is a test that never asserted a rule.

Verification: `bash .pi/scripts/freeze.sh verify --module billing`
(`contracts` · `frozen signatures` · `no placeholders` · `AC references` · `red state` · `dependencies`).

---

## 5. Explicitly out of scope for Phase A

| Not here | Why |
|---|---|
| `src/billing/infrastructure/**` adapters (models, repositories, parser, migration) | behaviour; Phase B. The package exists (with a docstring) so the DDD layer gate stays satisfied; it contains no adapter. |
| `src/billing/interfaces/http/**` (router, Pydantic schemas) | behaviour; Phase B. The package exists (with a docstring); the endpoint shape is frozen in §2.10. Registration in the app shell is the runtime-integration item. |
| Mandate digest-review adapter | cross-context call; the **port** is frozen (§2.9), the adapter arrives with the persistence item. |
| `billing_outbox` writer | needs the session factory and the unit of work. |

Rejecting these is the point of a freeze: the 10 failing tests are the specification, and each one maps
to an invariant in §1.