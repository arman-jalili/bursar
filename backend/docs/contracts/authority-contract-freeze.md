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

Frozen: **signatures, types, the refusal vocabulary, the invariant ids, the two domain-service
interfaces, the twelve event payload schemas, and the HTTP contract**. Every body raises
`NotImplementedError("A-n — see module doc")`. The single exception is `new_id()` — a uuid factory is not
behaviour, and stubbing it would force every test to invent identifiers.

Not frozen (Phase B): behaviour bodies, SQLAlchemy models, migration `003_authority`, the router
implementation, the `authority_outbox` writer, and **the EIP-712 signer/verifier implementation**. The
approval is frozen as a *binding contract* (A-13…A-15); how a signature is recovered is an adapter
concern, and a freeze that shipped it would hide which guarantees are still missing. The *shape* of
every endpoint and every event is frozen (§2.8, §2.9) — only the code that serves them is not.

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
        cls,
        attempt: AttemptView,
        mandate: MandateView,
        invoice: InvoiceView,
        *,
        household_id: str = "",
    ) -> PaymentIntent: ...  # A-2 … A-4
    @classmethod
    def from_reads(
        cls,
        *,
        invoice_id,
        payee,
        constitution_version,
        require_signature_for_new_payee,
        threshold,
        amount,
    ) -> PaymentIntent: ...
    def signed_payload(self) -> dict[str, Any]: ...  # A-1/A-13
    def typed_data_hash(self) -> str: ...  # A-13
```

Frozen for two reasons. `slots=True, frozen=True` makes A-1 unrepresentable-if-violated rather than a
convention. And the parameter list is the ACL: `issue` takes **views**, not a proposal, so a caller cannot
pass a `payee_address` even if it wants to.

`issue` is the synchronous convenience that re-reads `MandateView` (and fails closed if it cannot); an
async application service pre-reads the views and uses `from_reads`, so the aggregate never needs an event
loop. `typed_data_hash` is the single canonical hash of `signed_payload()` that every approval binds to.

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
    signature_hex: str; signer: EvmAddress; signed_digest: str = ""
    def covers(self, typed_data_hash: str, owner: EvmAddress) -> bool               # A-13/A-15
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

`signed_digest` is what makes the binding checkable without crypto in the domain: the binder recovers the
signature and records the digest it covered, and `covers()` compares that digest to the approval's. An
empty digest proves nothing about *which* intent was signed, so it is rejected — a proof that does not
say what it signed is exactly the replay A-13 forbids.

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

### 2.8 Domain events — `domain/events.py`

Wire names are stable (they are sealed into evidence envelopes and keyed by subscribers); payload
fields are frozen. Exactly twelve events exist, matching the module doc table — no thirteenth.

| Wire name (`event_name`) | Class | Payload fields |
|---|---|---|
| `PaymentIntentIssued` | `PaymentIntentIssued` | `intent_id, invoice_id, payee_id, payee_address, amount_micro_usdc, bank_digest, is_new_payee, requires_owner_signature, constitution_version` |
| `AuthorityDetermined` | `AuthorityDetermined` | `determination_id, intent_id, verdict, reason_codes, constitution_version, payee_status, read_at_iso` |
| `PaymentAllowed` | `PaymentAllowed` | `intent_id, amount_micro_usdc, reservation_id` |
| `PaymentRefused` | `PaymentRefused` | `intent_id, reason_codes, refused_at_iso` |
| `CapacityReserved` | `CapacityReserved` | `day, reservation_id, intent_id, amount_micro_usdc, committed_micro_usdc, reserved_micro_usdc` |
| `CapacityRefused` | `CapacityRefused` | `day, intent_id, amount_micro_usdc, headroom_micro_usdc` |
| `ApprovalRequested` | `ApprovalRequested` | `approval_id, intent_id, typed_data_hash, expires_at_iso, reason` |
| `ApprovalGranted` | `ApprovalGranted` | `approval_id, intent_id, signer` |
| `ApprovalRejected` | `ApprovalRejected` | `approval_id, intent_id, reason` |
| `ApprovalExpired` | `ApprovalExpiredEvent` | `approval_id, intent_id, expired_at_iso` |
| `CapacityCommitted` | `CapacityCommitted` | `day, reservation_id, intent_id, amount_micro_usdc, committed_micro_usdc` |
| `CapacityReleased` | `CapacityReleased` | `day, reservation_id, intent_id, amount_micro_usdc, reason` |

* **`ApprovalExpiredEvent`**, not `ApprovalExpired`: `domain/errors.py` already owns that name for the
  refusal. The **wire name stays `ApprovalExpired`** — subscribers and evidence key on it.
* Amounts are `*_micro_usdc` integers (ADR-002). The module doc table abbreviates them as `amount_usdc`;
  the unit is the contract, so the field name says it.
* Timestamps are ISO-8601 strings with an explicit offset (`*_iso`), so the sealed bytes do not depend on
  the consumer's datetime library.
* **`PaymentIntentIssued` is the one routing-bearing event:** it carries `payee_address` and
  `bank_digest` because Settlement cannot dispatch from an event that omits the destination. Both are
  copied from Mandate's verified record at issue time, never from the proposal (A-2) — provenance, not
  absence, is the guarantee. Every other event stays routing-free (`presented_digest`/`bank_digest` are
  digests, never account numbers).
* `PaymentAllowed` is the **only** event that authorises dispatch (A-8). `ESCALATE` publishes
  `ApprovalRequested`; `PaymentAllowed` follows only after a verified owner signature.

**Consumed, not owned:** Authority consumes Settlement's confirmed/reverted outcome events to run
`ReconcileReservation`. The inbound contract Authority requires is `event_id`, `reservation_id` (or
`intent_id`), `outcome` (`confirmed` | `reverted`) and `tx_hash`; delivery is at-least-once, so the
subscriber deduplicates on `(event_id, handler)` (ADR-003). Authority does **not** declare a second
`SettlementConfirmed` class — two definitions of one fact drift, and the publisher owns the schema.

### 2.9 HTTP contract and error envelope

Route handlers are **concrete** — `src/authority/interfaces/http/` gets a router and Pydantic schemas,
not a second interface file. The frozen part is the endpoint shape, which Rigorix and the console are
built against (ADR-004, NFR-003):

| Method | Path | Request | Success | Refusals / failure |
|---|---|---|---|---|
| `POST` | `/v1/precondition/check` | `intent_id, invoice_id, payee_id, amount_micro_usdc` (run-command params; anything routing-bearing is rejected, A-2) | `200 {decision, reason_codes, determination_id}` | **any non-2xx fails closed** — `409` refusal codes, `422 VALIDATION_FAILED`, `503` upstream unreadable |
| `POST` | `/v1/attempts/{attempt_id}/evaluate` | — | `200 DeterminationView` | `409` refusal codes, `422` |
| `GET` | `/v1/intents/{id}` | — | `200 IntentView` | `404 NOT_FOUND` |
| `GET` | `/v1/intents/{id}/determination` | — | `200 DeterminationView` (verdict + reason codes + version + `read_at`) | `404 NOT_FOUND` |
| `GET` | `/v1/ledger/{day}` | — | `200 {cap_micro_usdc, committed_micro_usdc, reserved_micro_usdc, headroom_micro_usdc}` | `404 NOT_FOUND` |
| `GET` | `/v1/approvals` | `?status=pending` | `200 ApprovalView[]` | — |
| `POST` | `/v1/approvals/{id}/signature` | `signature_hex` | `200 {granted: true}` | `409 APPROVAL_INVALID` (`binding_mismatch` / `single_use` / `expired`) |
| `POST` | `/v1/settlements/{id}/outcome` | `confirmed` \| `reverted`, `tx_hash` | `200` ledger state | `409 CONFLICT` (already resolved), `404 NOT_FOUND` |

**Fail-closed is a status-code contract, not a body convention (AC 11).** When Mandate cannot be read,
`POST /v1/precondition/check` returns `503` (never `200`) with `retryable: true`; Rigorix's client must
treat anything other than `200` as "do not run the command". A `200` body still authorises dispatch only
when `decision == "allow"`; `escalate` requires a verified signature and `deny` never dispatches.

The upstream-unavailable case reuses the shared closed `ErrorCode` set (`INTERNAL`, `retryable: true`)
rather than inventing an Authority-only code: the contract that matters is the non-2xx status, and the
reason codes in a *determination* remain the closed `DenialReason` set (A-5).

Every failure uses the shared envelope — Authority adds no bespoke error body:

```json
{ "error": { "code": "CAP_EXCEEDED", "message": "…", "retryable": false,
             "correlation_id": "…", "details": { "intent_id": "…" } } }
```

`code` is the closed `ErrorCode` set (`CAP_EXCEEDED`, `APPROVAL_INVALID`, `AMOUNT_MISMATCH`,
`BUDGET_EXHAUSTED`, `PAYEE_FROZEN`, …), and `details` carries ids and field names only — never amounts
the caller did not send, and never routing data. Mutating endpoints accept `Idempotency-Key` (ADR-004);
the approval endpoint is additionally single-use by domain rule (A-14), so an idempotent replay returns
the original outcome without consuming twice.

### 2.10 Domain services — `domain/services.py`

```python
class DeterminationPolicy(ABC):
    def decide(
        self, *, intent, constitution, payee, ledger, read_at, duplicate_invoice=False
    ) -> Determination: ...  # A-5 … A-8


class ApprovalBinder(ABC):
    def typed_data(self, intent) -> Mapping[str, Any]: ...  # A-13
    def recover_signer(self, *, typed_data_hash, signature_hex) -> EvmAddress: ...  # A-15
```

`DeterminationPolicy` is a stateless function-object (the module doc's *Specification (composed)*
pattern), not a god service: it composes the constitution's threshold/flag, the payee's live
eligibility and the ledger's headroom, and every input comes from the same read as the verdict (A-6).
`duplicate_invoice` is Billing's fact passed in, not queried — a hidden read would make A-6
unverifiable.

`ApprovalBinder` owns the EIP-712 **document**, because the same field list must generate the Python
verifier and the Solidity checker (ADR-007). `typed_data` must agree with
`PaymentIntent.signed_payload()`; a behaviour test asserts equality rather than trusting two hand-kept
lists. Recovery answers *who signed*; `Approval.verify` compares that to the mandate owner (A-15) and
`Approval.consume` makes it single-use (A-14). A binder that also granted authority would make the
single-use rule impossible to test, so the split is part of the contract.


---

## 3. Refusal vocabulary — `domain/errors.py`

| Class | Invariant | HTTP |
|---|---|---|
| `AuthorityRefusal` (base) | — | 409 |
| `AmountMismatch` | A-3 | 409 |
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
| `src/authority/infrastructure/**` bodies (models, adapters, migration `003_authority`) | behaviour; Phase B. The empty package exists so the layer gate passes. |
| `src/authority/interfaces/http/**` (router, request/response models, `/v1/precondition`) | behaviour; Phase B. The endpoint shape is frozen in §2.9; registering it is Phase B. |
| **EIP-712 signer/verifier implementation** | adapter concern; the *interface* (`ApprovalBinder`) is frozen in §2.10 and the *binding* in A-13…A-15, the crypto is not |
| `authority_outbox` writer implementation | needs the session factory; the event payloads are frozen (§2.8), ADR-003 delivery is Phase B |
| Budget guard implementation (`BUDGET_EXHAUSTED`) | ADR-006; the reason code is frozen, the check is Phase B |

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