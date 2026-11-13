# Authority — Contract Freeze (Phase A)

**Module:** Authority (core subdomain, tactical depth)
**Status:** Frozen for implementation — 2026-11-13
**Canonical module doc:** [`.pi/architecture/modules/authority.md`](../../.pi/architecture/modules/authority.md)
**Depends on:** Mandate (implemented) · Billing (frozen at `79b4b6b`)
**Decisions:** [ADR-002](../../.pi/architecture/decisions/ADR-002-data-storage-strategy.md),
[ADR-003](../../.pi/architecture/decisions/ADR-003-cross-context-communication.md),
[ADR-004](../../.pi/architecture/decisions/ADR-004-api-design.md),
[ADR-005](../../.pi/architecture/decisions/ADR-005-authentication-authorization.md),
[ADR-007](../../.pi/architecture/decisions/ADR-007-compliance-engine-architecture.md)

---

## 1. What is frozen, and what is not

Frozen: **signatures, types, the refusal vocabulary, and the invariant ids**. Every body raises
`NotImplementedError("A-n — see module doc")`. The single exception is `new_id()` — a uuid factory is not
behaviour, and stubbing it would force every test to invent identifiers.

Not frozen (Phase B): behaviour bodies, SQLAlchemy models, migration `003_authority`, the HTTP router, the
`/v1/precondition` entrypoint, and **the EIP-712 signer/verifier implementation**. The approval is frozen as
a *binding contract* (A-13…A-15); how a signature is recovered is an adapter concern, and a freeze that
shipped it would hide which guarantees are still missing.

**Fifteen invariants. A test that does not defend one of them does not belong in this suite.**

| Id | Rule | Illegal state prevented | Defending suite |
|---|---|---|---|
| **A-1** | An issued intent is **immutable** — no setter, no bulk merge. | Late mutation between authorization and signature. | `aggregate-paymentintent/`, `value-objects-entity-vs-vo-justification/` |
| **A-2** | `payee_address` and `bank_digest` come from **Mandate's verified record**, never from the invoice or the proposal. | Prompt injection or a scam invoice substituting the destination. | `paymentintent-issue/`, `ports-to-upstream-contexts-acl/` |
| **A-3** | `amount` must **equal the invoice amount**; an agent-supplied amount is not accepted. | Splitting one bill into edited-amount attempts to dodge the threshold. | `paymentintent-issue/` |
| **A-4** | `requires_owner_signature` is **derived** (new payee OR amount > threshold), never passed in. | The agent waiving its own escalation. | `requires-owner-signature/`, `domain-services/` |
| **A-5** | A `DENY` carries **at least one code** from the closed `DenialReason` set. | Refusals that cannot be explained or asserted in tests. | `determination-reasons/`, `no-llm/` |
| **A-6** | `constitution_version` and `payee_status_read` come from the **same read** as the verdict, with `read_at`. | A determination justified by a version it never actually consulted (scenario 3). | `re-read-rule/`, `aggregate-determination/` |
| **A-7** | A determination cannot exist **without a reason** (deny) or **without a version** (always). | Silent or unjustified verdicts. | `aggregate-determination/`, `determination-reasons/` |
| **A-8** | A `DENY` produces **no reservation and no dispatch**. | A refusal leaving a partial side effect (reserved capacity, queued order). | `refusal-has-no-side-effect/`, `layer-purity/` |
| **A-9** | `committed + reserved + amount <= cap`, checked and applied as **one** conditional update. | Concurrent split attempts each seeing headroom and jointly overdrawing the cap (scenario 4). | `capledger-cap/`, `aggregate-capledger/`, `repository-interfaces-owned-by-domain/` |
| **A-10** | A reservation resolves **exactly once** — committed or released, never both, never twice. | Double-counting or losing money relative to the chain. | `capledger-commit-release/`, `ledger-consistency/`, `entity-reservation-entity-approval/` |
| **A-11** | `committed` never decreases within a day; only `reserved` moves back down. | Un-committing settled spend to free headroom. | `ledger-consistency/` |
| **A-12** | The **day key is fixed** per reservation; a rollover creates a new ledger row. | A late settlement landing in tomorrow's cap. | `ledger-consistency/`, `entity-reservation-entity-approval/` |
| **A-13** | An approval binds `intent_id` + `amount` + `payee_address` + `bank_digest`; **any mismatch invalidates it**. | An approval for a 20 USDC bill replayed for a 320 USDC payment (scenario 5, negative). | `approval-binding/` |
| **A-14** | An approval is **single-use and expiring**; consuming it twice is impossible. | One owner signature dispatching two payments; a standing unlimited authority. | `approval-single-use/`, `approvals-expire/` |
| **A-15** | The **recovered signer must equal the mandate owner**. | A signature from any other key, including the operator's. | `approval-binding/`, `layer-purity/` |

---

## 2. Frozen signatures — `src/authority/`

### 2.1 Values — `domain/values.py`

```python
Money                     # re-exported from src/shared/domain/money.py — NOT redefined
class DeterminationVerdict(StrEnum):  ALLOW | DENY | ESCALATE
class DenialReason(StrEnum):          DIGEST_MISMATCH | PAYEE_QUARANTINED | PAYEE_FROZEN |
                                      CAP_EXCEEDED | DUPLICATE_INVOICE | APPROVAL_INVALID |
                                      BUDGET_EXHAUSTED | AMOUNT_MISMATCH
```

`Money` is imported rather than declared: two money types would eventually disagree about rounding, and the
ledger is exactly where that would hurt. The other two are **closed sets** — a verdict that is not one of
three, or a denial without a code, cannot be constructed (A-5, A-7), because a refusal must be explainable
*and* assertable.

### 2.2 `PaymentIntent` — `domain/payment_intent.py`

```python
@dataclass(frozen=True, slots=True)
class PaymentIntent:
    id: IntentId
    invoice_id: str
    payee_id: str
    payee_address: PayeeAddress
    amount: Money
    bank_digest: BankDigest
    is_new_payee: bool
    requires_owner_signature: bool
    constitution_version: int

    @classmethod
    def issue(
        cls, attempt: AttemptView, mandate: MandateView, invoice: InvoiceView
    ) -> PaymentIntent: ...  # A-2
    def signed_payload(self) -> dict[str, Any]: ...  # A-1/A-13
```

Frozen for two reasons. `slots=True, frozen=True` makes A-1 unrepresentable-if-violated rather than a
convention. And the parameter list is the ACL: `issue` takes **views**, not a proposal, so a caller cannot
pass a `payee_address` even if it wants to.

### 2.3 `Determination` — `domain/determination.py`

```python
@dataclass(frozen=True, slots=True)
class Determination:
    id: DeterminationId; intent_id: IntentId; verdict: DeterminationVerdict
    reason_codes: tuple[DenialReason, ...]; constitution_version: int
    payee_status_read: PayeeStatus; read_at: datetime; ledger_snapshot: Money

    @classmethod allow(cls, *, intent_id, constitution_version, payee_status_read, read_at, ledger_snapshot)
    @classmethod deny(cls, *, intent_id, reasons, constitution_version, payee_status_read, read_at, ledger_snapshot)
    @classmethod escalate(cls, *, intent_id, constitution_version, payee_status_read, read_at, ledger_snapshot)
    @property permits_dispatch -> bool          # A-8: ALLOW only; ESCALATE needs an approval
    def assert_not_a_refusal(self) -> None      # A-8 guard, raises DispatchWithoutAuthority
```

Every factory is keyword-only: the three constructors differ only in *what they know*, and positional
arguments would make `deny(..., version, status)` swappable with `escalate(...)` — a silent mis-recording of
the very basis A-6 requires.

### 2.4 `CapLedger` + `Reservation` — `domain/cap_ledger.py`

```python
class ReservationStatus(StrEnum):  HELD | COMMITTED | RELEASED

@dataclass(eq=False)
class Reservation:                                   # entity: identity + one-way lifecycle
    id: ReservationId; intent_id: IntentId; amount: Money; day: str
    expires_at: datetime; status: ReservationStatus
    @classmethod hold(cls, intent_id, amount, day, expires_at) -> Reservation      # A-10/A-12
    def mark_committed(self) -> None                                               # A-10
    def mark_released(self) -> None                                                # A-10

@dataclass(eq=False)
class CapLedger(AggregateRoot):
    day: str; cap: Money; committed: Money; reserved: Money
    @property headroom -> Money                                                    # A-9
    def try_reserve(self, intent_id, amount, expires_at) -> Reservation            # A-9, raises CapExceeded
    def commit(self, reservation) -> None                                          # A-10/A-11
    def release(self, reservation) -> None                                         # A-10
```

`try_reserve` is named `try_` on purpose: it refuses instead of over-booking, and returns the hold rather
than a bool so the caller cannot mistake "no exception" for "reserved".

### 2.5 `Approval` + `OwnerSignature` — `domain/approval.py`

```python
@dataclass(frozen=True, slots=True)
class OwnerSignature(ValueObject):    # proof artifact: no lifecycle, compares by content
    signature_hex: str; signer: EvmAddress
    def matches(self, intent: PaymentIntent, owner: EvmAddress) -> bool            # A-13/A-15

@dataclass(eq=False)
class Approval:                       # entity: identity, single-use, expiring
    id: ApprovalId; intent_id: IntentId; typed_data_hash: str; expires_at: datetime
    consumed_at: datetime | None; signature: OwnerSignature | None
    @classmethod request(cls, intent, *, expires_at) -> Approval                    # A-13
    def verify(self, signature, *, owner, now) -> None                             # A-13/A-15
    def consume(self, *, now) -> None                                              # A-14
    @property is_usable -> bool                                                    # A-14
```

The binding is **one digest** (`typed_data_hash`) over the intent's fields, not a field-by-field comparison:
comparing fields one by one is how a forgotten field becomes a hole (A-13).

### 2.6 Ports — `domain/repositories.py`, `domain/ports.py`

```python
PaymentIntentRepository    add · find_by_id · save              # no update path: A-1
DeterminationRepository    append · find_by_intent              # no save: a verdict is final (A-7)
CapLedgerRepository        try_reserve_atomic(day, amount, reservation) -> bool
                           resolve(reservation_id, outcome) · ledger_for(day)
ApprovalRepository         add · find_by_id · find_pending · save

MandateView (Protocol)     constitution_in_force · payee · eligibility      # read-through, A-6
AttemptViewPort (Protocol) load(attempt_id) -> (AttemptView, InvoiceView)   # ACL, A-2
```

Three signatures carry invariants rather than describing storage:

* **`try_reserve_atomic -> bool`** is A-9 in a signature: one conditional `UPDATE`, `False` when it matched
  no row. Returning the ledger would invite read-then-write.
* **`DeterminationRepository` has no `save`** — an append-only port cannot revise a verdict.
* **`AttemptView` has no routing fields at all** (`payee_address`, `bank_digest`, `command`, `cap`,
  `threshold`) — A-2 becomes structural instead of a rule someone must remember.

No port exposes `commit`/`flush`/`begin`: the unit of work belongs to `application/` (ADR-002).

### 2.7 Application services — `application/services.py` (FR-011 … FR-017)

```python
EvaluateAuthority       intent + determination + reservation
ReserveCapacity         the atomic hold (raises CapExceeded)
EscalateForSignature    bind a request to one intent
SubmitOwnerSignature    verify + consume, or refuse with no side effect
ReconcileReservation    commit or release, exactly once
```

Commands carry **ids and an optional claimed amount only** — no address, no digest, no cap (A-2, A-3). One
service = one `session_scope` = one outbox append (ADR-003).

---

## 3. Refusal vocabulary — `domain/errors.py`

| Class | Invariant | HTTP |
|---|---|---|
| `AuthorityRefusal` (base) | — | 409 |
| `CapExceeded` | A-9 | 409 |
| `ReservationAlreadyResolved` | A-10 | 409 |
| `DeterminationWithoutReason` | A-5, A-7 | 422 |
| `ApprovalBindingMismatch` | A-13 | 409 |
| `ApprovalSingleUse` | A-14 | 409 |
| `ApprovalExpired` | A-14 | 409 |
| `DispatchWithoutAuthority` | A-8 | 409 |

All extend the shared `RefusalError`, so the transport needs **no Authority-specific handling**: a refusal is
a documented `409` with a domain code (ADR-004), never a `500`.

---

## 4. Ordered Phase-B work list

1. `Money`-based parsing + `DeterminationVerdict`/`DenialReason` guards (fast, no I/O).
2. `PaymentIntent.issue` + `signed_payload` — A-2, A-3, A-4.
3. `Determination.allow/deny/escalate`, `permits_dispatch`, `assert_not_a_refusal` — A-5…A-8.
4. `CapLedger` + `Reservation` — A-9…A-12, then the conditional-`UPDATE` adapter and the **six-racer
   concurrency test** (scenario 4) before any UI work.
5. `Approval` + `OwnerSignature` — A-13…A-15, including expiry and single-use.
6. `MandateView` / `AttemptViewPort` adapters (read-through, no cache) + contract tests for scenario 3.
7. `EvaluateAuthority`, `ReserveCapacity`, `EscalateForSignature`, `SubmitOwnerSignature`,
   `ReconcileReservation` — in that order, one `session_scope` each.
8. `POST /v1/precondition/check` fail-closed behaviour (AC 11) + Rigorix integration test.
9. Migration `003_authority`, then wiring into `authority-service`'s `HOSTED_CONTEXTS`.

---

## 5. Explicitly out of scope for Phase A

| Not here | Why |
|---|---|
| `src/authority/infrastructure/**` (models, adapters, migration `003_authority`) | behaviour; Phase B |
| `src/authority/interfaces/http/**` (router, schemas, `/v1/precondition`) | behaviour; registering it is Phase B |
| **EIP-712 signer/verifier implementation** | adapter concern; the *binding* is frozen (A-13…A-15), the crypto is not |
| `authority_outbox` writer, event payloads | needs the session factory; ADR-003 delivery is Phase B |
| Domain events (`PaymentIntentIssued` … `CapacityReleased`) | payload schemas land with the services that publish them |
| Budget guard (`BUDGET_EXHAUSTED`) | ADR-006; the reason code is frozen, the check is Phase B |

---

## 6. Red state — what "the tests fail for the right reason" means

`bash .pi/scripts/freeze.sh verify --module authority` must report `red state: red_ok` — the suite fails
because behaviour is missing (`NotImplementedError: A-n`), never because of an import or syntax error.

Known and intended: a small number of assertions pass **today** because they defend rules that are already
true by construction — the ports have no `commit`, `MandateView` has no cached variant, the verdict set is
closed, `OwnerSignature` compares by content, the fail-closed port raises when its upstream is unreachable.
Those cannot be made to fail without faking a stub, and they are the rules that would silently rot if nobody
asserted them. Every *behavioural* assertion in the suite is red.

When Phase B implements a body, its test must go green **and stay green**; a test that turns green without a
behaviour change never asserted a rule.