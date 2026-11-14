# Settlement — Contract Freeze (Phase A)

**Module:** Settlement (core subdomain, tactical depth)
**Status:** Frozen for implementation — 2026-11-14
**Canonical module doc:** [`.pi/architecture/modules/settlement.md`](../../.pi/architecture/modules/settlement.md)
**Decisions:** [ADR-001](../../.pi/architecture/decisions/ADR-001-architecture-pattern.md),
[ADR-002](../../.pi/architecture/decisions/ADR-002-data-storage-strategy.md),
[ADR-003](../../.pi/architecture/decisions/ADR-003-cross-context-communication.md),
[ADR-004](../../.pi/architecture/decisions/ADR-004-api-design.md),
[ADR-006](../../.pi/architecture/decisions/ADR-006-cost-tracking-usage-metering.md),
[ADR-007](../../.pi/architecture/decisions/ADR-007-compliance-engine-architecture.md)

---

## 1. What is frozen, and what is not

Frozen: **signatures, types, the refusal vocabulary with its status codes, the seven event payload
schemas, the three ports, the three repository interfaces, and the twelve invariant ids**. Every
behaviour body is `raise NotImplementedError("SC-n — see module doc")`, so the module cannot do anything
yet — by design. The only executable body is `domain.ids.new_id()`: identifier generation is not
behaviour, and stubbing it would force every test to invent ids.

Not frozen (Phase B, implementation): behaviour bodies, SQLAlchemy models, migrations, the HTTP router,
`PaymentRouter.sol` and its Anvil deployment, the Rigorix/web3/Authority adapters, and the outbox writer.
Phase A deliberately ships **no** adapter: a contract freeze that also writes persistence is not a
freeze, and it hides which guarantees are still missing.

`SC-n` is the contract id; `AC-n` is the matching row of the module doc's Acceptance Criteria table. The
two are deliberately one-to-one: the module doc is canonical, and this file is its checkable form.

**The twelve invariants below are the module's whole reason to exist.** A test that does not defend one
of them does not belong in the suite.

| Id | Rule (what must be true) | Illegal state prevented | Defended by |
|---|---|---|---|
| **SC-1** | An order is creatable only from a determination whose verdict permits dispatch (`allow`, or `escalate` that became `ApprovalGranted`); otherwise `DispatchWithoutAuthority` and no order exists. | Dispatching a payment nobody authorised (AC-1). | `tests/unit/settlement/settlementorder-order/` |
| **SC-2** | The dispatch command path is the module constant `payments.dispatch`; it is a `ClassVar`, and `command_params()` takes no arguments. | A prompt injection redirecting the settlement command (AC-2). | `tests/unit/settlement/command-params/` |
| **SC-3** | The tx hash is persisted before broadcast; an order never gets a second hash, and re-polling the persisted hash is not a new transaction. | A retry generating a new nonce and paying twice (AC-3). | `tests/unit/settlement/write-ahead-hash/` |
| **SC-4** | An order concludes exactly once; a concluded order cannot be re-concluded, re-submitted or reset. | Error paths that resurrect a duplicate payment (AC-4). | `tests/unit/settlement/conclude/` |
| **SC-5** | The nullifier is `keccak(invoice_hash, scope)`; a spent marker is refused locally (`DuplicateSettlementBlocked`) before any chain call, and the store refuses a second spend. | A settled invoice replayed through the API (scenario 6, AC-5). | `tests/unit/settlement/nullifier-local/`, `tests/unit/settlement/repository-interfaces-owned-by-domain/` |
| **SC-6** | A revert is a refusal: it concludes the order as `REVERTED`, is recorded once, and is never retried — even when the app is bypassed, the contract reverts on the spent nullifier. | The timeout double-pay; a bypass that pays anyway (scenario 6, AC-6). | `tests/unit/settlement/nullifier-on-chain/` |
| **SC-7** | Finality is a confirmation count taken from `ChainNetwork`: below it the order is `PENDING` with no cap commit, at/above it `CONFIRMED` and the commit; concluding early raises `SettlementNotFinal`. | Committing a cap on a transaction a reorg can remove (AC-7). | `tests/unit/settlement/finality/` |
| **SC-8** | A reverted order is terminal and produces exactly one outbox `SettlementReverted`; a refused dispatch produces no transaction at all. | An implicit retry that turns one refusal into two payments (AC-8). | `tests/unit/settlement/revert-refusal/` |
| **SC-9** | The amount submitted equals the amount signed on the intent; a mismatch is refused at submit (`AmountIntegrityViolation`) and the command amount is read from the frozen order. | Paying an edited amount the owner never signed (AC-9). | `tests/unit/settlement/amount-integrity/` |
| **SC-10** | Every receipt records `gas_used`, `gas_price` and `fee_usdc_estimate`; a receipt without cost is refused (`ReceiptCostMissing`); `CostSummary` derives from receipts only, anchors included. | A cost ledger that under-reports what the chain charged (AC-10, ADR-006). | `tests/unit/settlement/receipt-cost/` |
| **SC-11** | Anvil and Base Sepolia each carry their own chain id, router, USDC and confirmation count; an unconfigured chain id is refused (`UnknownNetwork`) rather than defaulted. | A hardcoded address leaking between networks (AC-11). | `tests/unit/settlement/network-config/`, `tests/unit/settlement/value-objects-entity-vs-vo-justification/` |
| **SC-12** | `src/settlement/domain/` imports no `web3`/`httpx`/`fastapi`, does not import outward layers, and every refusal it raises is a `SettlementRefusal` (a shared `RefusalError`). | A domain that needs the chain to be unit-tested; a refusal surfacing as a 500 (AC-12). | `tests/unit/settlement/layer-purity/`, `tests/unit/settlement/ports-infrastructure-adapters/` |

### Module-doc invariants S-1 … S-6

The module doc states six aggregate-local invariants. They are not a second system: `S-1…S-6` are the
aggregate-local form of `SC-1…SC-4`, `SC-6`, `SC-9`.

| Module doc | Contract id | Note |
|---|---|---|
| S-1 authority required | SC-1 | Enforced at the only entry point, `SettlementOrder.order`. |
| S-2 payee/amount/nullifier frozen from the intent | SC-2, SC-9 | The address type is Mandate's; the command reads the order's fields. |
| S-3 write-ahead hash, one hash | SC-3 | `mark_submitted` keeps the first hash and refuses a different one. |
| S-4 conclude once | SC-4 | `OrderAlreadyConcluded` on the second call. |
| S-5 command path is a module constant | SC-2 | **Amended:** `command_ref` is a `ClassVar`, not a field (see §2.3). |
| S-6 revert is terminal | SC-6, SC-8 | A revert maps to `REVERTED` and a `SettlementReverted` event. |

---

## 2. Frozen signatures — `src/settlement/`

### 2.1 Identifiers — `domain/ids.py`

```python
OrderId  = NewType("OrderId", str)
ReceiptId = NewType("ReceiptId", str)
AnchorId = NewType("AnchorId", str)
IntentId = <re-exported from src.authority.domain.ids>

def new_id() -> str: ...   # uuid4 hex — the only executable body in the freeze
```

`IntentId` is Authority's, re-exported rather than re-declared: both contexts must address the same
`intent_id` value (the context map's `intent_id` contract). The three local ids exist because the
endpoints and the outbox key on different things, and swapping an order id for a receipt id is a
realistic bug the checker catches for free.

### 2.2 Value objects — `domain/values.py`

```python
@dataclass(frozen=True, slots=True)
class Nullifier(ValueObject):
    value: str                                   # "0x" + 32-byte hex — the on-chain key shape

    @classmethod
    def derive(cls, invoice_hash: str, scope: str) -> Nullifier: ...   # SC-5
    def same_as(self, other: Nullifier) -> bool: ...                   # SC-5


@dataclass(frozen=True, slots=True)
class ChainNetwork(ValueObject):
    chain_id: int
    router_address: str
    usdc_address: str
    confirmations_required: int

    @classmethod
    def anvil(cls) -> ChainNetwork: ...                     # SC-11
    @classmethod
    def base_sepolia(cls) -> ChainNetwork: ...              # SC-11
    @classmethod
    def for_chain(cls, chain_id: int) -> ChainNetwork: ...  # SC-11, raises UnknownNetwork
```

**`PayeeAddress` is not redefined here.** Settlement is conformist to Mandate (context map), so the
address carried on the intent is `src.mandate.domain.values.PayeeAddress`, validated by the context that
owns it. The module doc's component table lists `PayeeAddress` under Settlement's domain; the frozen
interpretation is "settlement uses Mandate's value object", because a second address type would let one
side accept a destination the other rejects.

**Nullifier derivation must be keccak256**, not `hashlib.sha3_256`: the EVM's `keccak256` and SHA3-256
are different functions, so a mismatch would never collide with the on-chain map. AC-12 forbids `web3`
in `domain/`, so the Phase-B value-objects item picks a keccak implementation usable in the domain
(e.g. `eth-hash` / a small pure implementation) — this is the one new dependency the freeze permits.

### 2.3 `SettlementOrder` — `domain/settlement_order.py` (aggregate root)

```python
PAYMENT_COMMAND = "payments.dispatch"

@dataclass(eq=False)
class SettlementOrder(AggregateRoot):
    id: OrderId
    intent_id: IntentId
    invoice_id: str
    payee_address: PayeeAddress
    amount: Money
    nullifier: Nullifier
    network: ChainNetwork
    status: SettlementStatus
    tx_hash: str | None = None

    command_ref: ClassVar[str] = PAYMENT_COMMAND      # no constructor argument, no instance field

    @classmethod
    def order(cls, intent: PaymentIntentView, network: ChainNetwork,
              determination: DeterminationView) -> SettlementOrder: ...   # SC-1
    def command_params(self) -> dict[str, object]: ...                     # SC-2, SC-9
    def mark_submitted(self, tx_hash: str, signed_amount: Money) -> None: ...  # SC-3, SC-9
    def conclude(self, receipt: ChainReceipt) -> None: ...                 # SC-4, SC-6, SC-7
```

Two contract decisions are recorded here:

* **`command_ref` is a `ClassVar`, not a dataclass field.** The module-doc stub shows a field with a
  default, which would let a caller write `SettlementOrder(..., command_ref="payments.anything")` —
  exactly what AC-2 says must be impossible. A `ClassVar` means there is no argument and no field to
  taint. This is an **amendment** to the module doc, recorded here and referenced from its
  `## Contract Freeze` section.
* **`mark_submitted` takes the signed amount.** It is the only point where "what will move" and "what the
  owner signed" are both in hand, so SC-9 is checked there instead of asserted in a comment.

There is no setter and no `update(**fields)`: `status` moves through intention methods only, which is
what keeps SC-3/SC-4 enforceable.

### 2.4 Read models — `domain/views.py`

```python
@dataclass(frozen=True, slots=True)
class PaymentIntentView:
    intent_id: IntentId
    invoice_id: str
    payee_address: PayeeAddress
    amount: Money
    invoice_hash: str          # Billing's identity for the bill — the nullifier seed (SC-5)
    household_id: str          # Mandate's household reference — the nullifier scope (SC-5)
    bank_digest: BankDigest
    is_new_payee: bool = False
    requires_owner_signature: bool = False


@dataclass(frozen=True, slots=True)
class DeterminationView:
    intent_id: IntentId
    verdict: DeterminationVerdict
    approval_granted: bool = False
    determination_id: str = ""

    def permits_dispatch(self) -> bool: ...   # SC-1
```

`PaymentIntentView` adds two fields Authority's `PaymentIntent` aggregate does not store —
`invoice_hash` (Billing's identity, the nullifier seed) and `household_id` (the scope). Phase B
assembles the view in the application layer from `PaymentIntent` + Billing's invoice hash + Mandate's
household reference; the domain never reaches across a context. `DeterminationView` exists so the
allow/escalate-approved rule lives in one predicate instead of three verdict-string comparisons.

### 2.5 `ChainReceipt` — `domain/chain_receipt.py` (entity)

```python
@dataclass(frozen=True, slots=True)
class ChainReceipt:
    id: ReceiptId
    order_id: OrderId
    tx_hash: str
    block_number: int
    confirmations: int
    status: ReceiptStatus
    gas_used: int                # required — SC-10
    gas_price: str               # wei as a decimal string
    fee_usdc_estimate: Money     # required — SC-10
    is_anchor: bool = False
    revert_reason: str = ""

    def __post_init__(self) -> None: ...              # SC-10, raises ReceiptCostMissing
    def is_final(self, confirmations_required: int) -> bool: ...   # SC-7
    @property
    def confirmed(self) -> bool: ...                  # SC-7 (status SUCCESS, depth-independent)
```

Cost fields are **non-optional**: a receipt that omits its cost would make `CostSummary` either wrong or
silently partial (ADR-006). A missing cost is a refusal, not a zero. `is_final` takes the network's count
because a receipt must not know a network's policy.

### 2.6 Domain services — `domain/services.py`

```python
class NullifierPolicy:
    def derive(self, invoice_hash: str, scope: str) -> Nullifier: ...        # SC-5
    def guard_unspent(self, nullifier: Nullifier, *, already_spent: bool) -> None: ...  # SC-5

class FinalityPolicy:
    def is_final(self, receipt: ChainReceipt, network: ChainNetwork) -> bool: ...       # SC-7
    def status_for(self, receipt: ChainReceipt, network: ChainNetwork) -> SettlementStatus: ...  # SC-7
```

`guard_unspent` takes the **fact** (`already_spent`) rather than a repository: the domain may not do
I/O, and the refusal then needs no database to be tested. The repository's unique constraint remains the
last local lock.

### 2.7 Repository ports — `domain/repositories.py`

```python
class SettlementOrderRepository(Repository[OrderId, SettlementOrder], ABC):
    async def add(self, order: SettlementOrder) -> None: ...            # SC-3, raises OrderAlreadyConcluded
    async def find_by_id(self, id_: OrderId) -> SettlementOrder | None: ...
    async def find_by_intent(self, intent_id: IntentId) -> SettlementOrder | None: ...   # SC-4 replay lookup
    async def save(self, order: SettlementOrder) -> None: ...


class NullifierRepository(ABC):
    async def is_spent(self, nullifier: Nullifier) -> bool: ...
    async def spend(self, nullifier: Nullifier, order_id: OrderId) -> None: ...  # SC-5, unique constraint


class ChainReceiptRepository(ABC):
    async def append(self, receipt: ChainReceipt) -> None: ...           # SC-10, append-only
    async def find_by_order(self, order_id: OrderId) -> ChainReceipt | None: ...
    async def list_for_day(self, day: date) -> tuple[ChainReceipt, ...]: ...   # SC-10
```

Ports are **owned by `domain/`** and declare **no transaction control** (`commit`, `flush`, `begin`) —
the unit of work belongs to the application layer (ADR-002). `add` is not `save`: insert refuses
duplicates, update does not, so the invariant is not hidden in an upsert. `list_for_day` exists so
`CostSummary` derives from receipts only.

### 2.8 Ports — `domain/ports.py`

**Amended (see §7):** `ChainGateway.submit` was split into `prepare` + `broadcast`. The frozen shape is
the one below; the reason it could not stay as it was is §7's subject.

```python
@dataclass(frozen=True, slots=True)
class CommandAck:
    command_ref: str           # the settlement command's identity (`payments.dispatch`, SC-2)
    accepted: bool
    precondition: str = ""
    execution_id: str = ""     # additive: the governed execution's id (= the order id)
    audit_uri: str = ""        # additive: the host's audit trail for this run
    command_text: str = ""     # additive (§7): the rendered command the host executed

@dataclass(frozen=True, slots=True)
class SignedPayment:
    tx_hash: str               # known before broadcast; this is what SC-3 persists
    raw_transaction: str       # 0x-hex of the signed bytes; public by definition

class PaymentExecutor(Protocol):
    async def execute(self, order: SettlementOrder) -> CommandAck: ...

class ChainGateway(Protocol):
    async def prepare(self, order: SettlementOrder) -> SignedPayment: ...
    async def broadcast(self, signed: SignedPayment) -> None: ...
    async def receipt(self, tx_hash: str) -> ChainReceipt | None: ...
    async def is_nullifier_spent(self, nullifier: Nullifier) -> bool: ...
    async def anchor(self, anchored_hash: str) -> str: ...

class DeterminationGate(Protocol):
    async def determination_for(self, intent_id: IntentId) -> DeterminationView: ...
```

* `PaymentExecutor` receives the **order**, not a params dict — the command path can only come from
  `order.command_params()` (SC-2).
* `ChainGateway.prepare` signs locally and sends nothing: the hash is known while nothing is on the
  wire, which is what makes SC-3's write-ahead ordering expressible. It MUST refuse
  (`SecondTransactionRefused`) when `order.tx_hash` is set — a second signature is a second nonce — and
  MUST refuse (`SettlementRefusal`) when `order.requires_owner_signature` (the settlement key cannot
  produce the owner's EIP-712 signature; A-15).
* `ChainGateway.broadcast` sends already-signed bytes and nothing else. It is idempotent-*safe*, not
  idempotent: the same bytes are the same transaction, and the on-chain nullifier is what refuses a
  second payment (SC-5). `submit` is gone: one call that signs *and* sends can only hand back a hash
  the caller could not have persisted first.
* `DeterminationGate` is a live read; there is no cached-verdict method (SC-1).
* Ports are `Protocol`s: methods are declarations (`...`), not bodies, so the freeze contains no logic.
  Adapters (`RigorixCommandAdapter`, `Web3ChainGateway`, `AuthorityHttpAdapter`) are Phase B.

### 2.9 Enumerations — `domain/values.py`

```python
class SettlementStatus(StrEnum):
    ORDERED | SUBMITTED | PENDING | CONFIRMED | REVERTED | ABANDONED

class ReceiptStatus(StrEnum):
    PENDING | SUCCESS | REVERTED
```

Both are closed. `CONFIRMED`, `REVERTED` and `ABANDONED` are terminal: a state that could re-open is how
a refusal becomes a retry (SC-4, SC-6, SC-8). `ABANDONED` keeps its tx hash forever and is never
re-signed (SC-3).

### 2.10 Application layer — `application/dto.py`, `application/services.py`

```python
@dataclass(frozen=True, slots=True)
class DispatchPaymentCommand:
    intent_id: str
    idempotency_key: str = ""        # no command, command_path, payee_address, amount or network field

@dataclass(frozen=True, slots=True)
class SettleOnceCommand:
    order_id: str

class DispatchPayment(ABC):
    async def execute(self, command: DispatchPaymentCommand) -> DispatchPaymentResult: ...   # SC-1, 5, 9
class SettleOnce(ABC):
    async def execute(self, command: SettleOnceCommand) -> SettleOnceResult: ...             # SC-4, 5, 6, 7
class GetReceipt(ABC):   async def execute(self, order_id: str) -> ReceiptView: ...
class ListOrders(ABC):   async def execute(self, query: ListOrdersQuery) -> tuple[OrderView, ...]: ...
class AnchorHash(ABC):   async def execute(self, command: AnchorHashCommand) -> AnchorHashResult: ...
class CostSummary(ABC):  async def execute(self, query: CostSummaryQuery) -> CostSummaryView: ...
```

Commands carry identifiers only. `DispatchPaymentCommand` has **no field for a network, a path or an
amount**; the network is resolved from configuration (SC-11). Amounts are integer micro-units in every
DTO (ADR-002). `ReceiptView` exposes gas and fee because the receipt is the only cost record; and
`CostSummaryView` is a derived projection, never a stored balance (ADR-006).

Each implementation opens exactly one `session_scope` and appends the drained events to
`settlement_outbox` in that same transaction (ADR-003), with two contract-level orderings: persist the
hash **then** broadcast (SC-3), and a revert ends the use case with no retry branch (SC-6, SC-8).

### 2.11 HTTP contract and error envelope

Route handlers are **concrete** — `src/settlement/interfaces/http/` gets a router and Pydantic schemas in
Phase B, not a second interface file. The frozen part is the endpoint shape (ADR-004):

| Method | Path | Request | Success | Refusals |
|---|---|---|---|---|
| `POST` | `/v1/intents/{intent_id}/dispatch` | `Idempotency-Key` header — **no body fields** | `201 order + tx hash` | `409 DISPATCH_WITHOUT_AUTHORITY`, `409 DUPLICATE_SETTLEMENT`, `409 AMOUNT_INTEGRITY_VIOLATION` |
| `GET` | `/v1/orders/{id}` | — | `200 OrderView` | `404 NOT_FOUND` |
| `GET` | `/v1/orders/{id}/receipt` | — | `200 ReceiptView` | `404 NOT_FOUND` |
| `GET` | `/v1/receipts` | `?day=` | `200 ReceiptView[] + CostSummaryView` | — |
| `GET` | `/v1/nullifiers/{value}` | — | `200 {spent, order_id}` | — |
| `POST` | `/v1/anchors` | `hash` | `201 {anchor_tx, anchored_hash}` | `422 VALIDATION_FAILED` |

`POST /v1/intents/{intent_id}/dispatch` accepts **no body**: there is no `command`, `payee_address` or
`amount` field for a caller to send (SC-2, SC-9). Every failure uses the shared envelope — Settlement
adds no bespoke error body:

```json
{ "error": { "code": "DUPLICATE_SETTLEMENT", "message": "…",
             "retryable": false, "correlation_id": "…",
             "details": { "nullifier": "0x…", "order_id": "…" } } }
```

`code` is the closed `ErrorCode` set; `details` carries ids/hex values only — never routing data.

### 2.12 Domain events — `domain/events.py`

Wire names are stable (sealed into evidence envelopes, keyed by subscribers); payload fields are frozen.
Exactly seven events exist, matching the module doc — no eighth.

| Wire name (`event_name`) | Class | Payload fields | Crosses boundary |
|---|---|---|---|
| `SettlementOrdered` | `SettlementOrdered` | `order_id, intent_id, invoice_id, nullifier, amount_micro_usdc, chain_id` | ✅ |
| `SettlementSubmitted` | `SettlementSubmitted` | `order_id, tx_hash, nonce` | ❌ (audit) |
| `SettlementConfirmed` | `SettlementConfirmed` | `order_id, intent_id, tx_hash, block_number, confirmations, amount_micro_usdc` | ✅ |
| `SettlementReverted` | `SettlementReverted` | `order_id, intent_id, tx_hash, revert_reason` | ✅ |
| `DuplicateSettlementBlocked` | `DuplicateSettlementBlockedEvent` | `intent_id, invoice_id, nullifier, detected_by` | ✅ |
| `NullifierSpent` | `NullifierSpent` | `nullifier, order_id, invoice_id` | ❌ (audit) |
| `ReceiptAnchored` | `ReceiptAnchored` | `anchor_tx, anchored_hash, order_id` | ✅ |

* **`DuplicateSettlementBlockedEvent`**, not `DuplicateSettlementBlocked`: `domain/errors.py` owns that
  name for the refusal. The **wire name stays `DuplicateSettlementBlocked`**.
* Amounts are `amount_micro_usdc` (ADR-002); the module doc's `amount_usdc` is a unit ambiguity the field
  name resolves. `occurred_at` replaces `detected_at` — every `DomainEvent` already carries the instant.
* **No routing fields, ever.** No `payee_address` on the wire: subscribers must not be tempted to route
  from an event.
* **Consumed, not owned:** Settlement consumes `PaymentAllowed` / `ApprovalGranted` (Authority) to run
  `DispatchPayment`. Delivery is at-least-once, so the subscriber dedupes on `(event_id, handler)`.

---

## 3. Refusal vocabulary — `domain/errors.py`

Every class extends the shared `RefusalError` (via `SettlementRefusal`), so the API layer needs **no
Settlement-specific exception handling**: a refusal is a documented error with a domain code everywhere
in this context, and it can never surface as a 500.

| Refusal | Code | Status | Invariant | Why a distinct class |
|---|---|---|---|---|
| `SettlementRefusal` | `CONFLICT` | 409 | base | one vocabulary for the context |
| `DispatchWithoutAuthority` | `CONFLICT` | 409 | SC-1 | no determination permits dispatch |
| `SecondTransactionRefused` | `CONFLICT` | 409 | SC-3 | a second hash is a second payment |
| `OrderAlreadyConcluded` | `CONFLICT` | 409 | SC-4 | concluding twice is a bug, not idempotency |
| `DuplicateSettlementBlocked` | `CONFLICT` | 409 | SC-5 | the nullifier is spent (local or on-chain) |
| `IllegalTransition` | `CONFLICT` | 409 | SC-3, SC-6, SC-8 | a transition that must be unrepresentable was attempted |
| `SettlementNotFinal` | `CONFLICT` | 409 | SC-7 | confirmation threshold not reached, no cap commit |
| `AmountIntegrityViolation` | `AMOUNT_MISMATCH` | 409 | SC-9 | signed amount ≠ submitted amount |
| `ReceiptCostMissing` | `VALIDATION_FAILED` | 422 | SC-10 | the adapter produced an incomplete fact |
| `UnknownNetwork` | `VALIDATION_FAILED` | 422 | SC-11 | an unconfigured chain, no default |

`409` for every state conflict. `422` only for `ReceiptCostMissing` and `UnknownNetwork`: both are
malformed *data* (an incomplete receipt; a chain nobody configured), not a conflict with an order's
state — the same documented carve-out Billing makes for `ProposalRejected`. `DUPLICATE_SETTLEMENT` is
Settlement's own reason code, not `DUPLICATE_INVOICE`: the latter belongs to Billing's *record a bill*
path, while this refusal is a conflict with a spent marker.

Payloads are explicit `details` mappings, never a `**kwargs` tail: a splat can smuggle a key named
`retryable` or `code` into `RefusalError` and silently rewrite the refusal's semantics.

---

## 4. Ordered Phase-B work list

Implement in this order; each step is independently testable and turns its suites green without
weakening another. Steps 1–2 are pure domain and need no chain.

1. **`ChainNetwork` (Anvil + Base Sepolia), `PayeeAddress` usage, `Nullifier.derive`** — the derivation
   test and the no-address-leak test go green (SC-5, SC-11). Pick the keccak implementation here (the one
   permitted new dependency).
2. **`SettlementOrder`** — `order`, `command_params`, `mark_submitted` (write-ahead + amount), `conclude`
   with SC-1…SC-6, SC-9. Suites: `settlementorder-order/`, `command-params/`, `write-ahead-hash/`,
   `conclude/`, `amount-integrity/`, `revert-refusal/`.
3. **`PaymentRouter.sol` (Foundry)** — nullifier map, EIP-712 check, anchor event; deploy to Anvil.
   Satisfies SC-5/SC-6 from the other side; the app-side tests stay unchanged.
4. **`ChainGateway` adapter** — submit, poll, parse revert reasons; receipt fixtures for tests
   (SC-3, SC-6, SC-7, SC-10).
5. **`NullifierRepository` + migration** — unique constraint; the local duplicate suite and the
   repository contract suite go green (SC-5).
6. **`DispatchPayment`** — Rigorix `run_command` with code-generated params, then the write-ahead submit
   (SC-1, SC-2, SC-3). Includes `DeterminationGate` + `AuthorityHttpAdapter`.
7. **`SettleOnce` + `FinalityPolicy`** — the on-chain duplicate path and the PENDING/CONFIRMED split
   (SC-4, SC-6, SC-7).
8. **Publish `SettlementConfirmed` / `SettlementReverted` to `settlement_outbox`** → Authority
   reconciliation (commit/release) (SC-7, SC-8).
9. **`AnchorHash` + `CostSummary`** (ADR-006, SC-10), then `GetReceipt`/`ListOrders` and the HTTP router
   (`§2.11`), then the runtime-integration registration in `console_api`.

---

## 5. Red state — what "the tests fail for the right reason" means

Every suite under `tests/unit/settlement/` asserts a **rule** and fails today because the behaviour above
is `NotImplementedError`. Expected and accepted:

* `pytest.raises(<SettlementRefusal subclass>)` around a stub raises `NotImplementedError` → **red**.
* The suite is red **as a whole**; four supporting assertions are green **by design**, and none of them
  is a green assertion over a `NotImplementedError` body:
  * `layer-purity`'s two import scans (SC-12) assert facts that are true today and must stay true;
  * `value-objects-entity-vs-vo-justification`'s two `PayeeAddress` tests assert a **Mandate**
    (implemented) rule that Settlement consumes — they would catch Settlement redefining the type.
* A test that asserts only shape (`isinstance`, `dataclass`, `hasattr`, member names) is **not**
  evidence and would be rejected: green assertions over `NotImplementedError` bodies prove nothing.
* As soon as a body is implemented, its test must go green **and** stay green; a test that turns green
  without a behaviour change is a test that never asserted a rule.

Verification: `bash .pi/scripts/freeze.sh verify --module settlement`
(`contracts` · `frozen signatures` · `no placeholders` · `AC references` · `red state` · `type check` ·
`test isolation` · `dependencies`).

---

## 6. Explicitly out of scope for Phase A

| Not here | Why |
|---|---|
| `src/settlement/infrastructure/**` adapters (web3, Rigorix, Authority HTTP, SQLAlchemy models, migration) | behaviour; Phase B. The package exists with a docstring so the DDD layer gate stays satisfied; it contains no adapter. |
| `src/settlement/interfaces/http/**` (router, Pydantic schemas) | behaviour; Phase B. Handlers are concrete by design — the endpoint shape is frozen in §2.11, not as an interface. |
| `PaymentRouter.sol`, Foundry tests, Anvil deployment | on-chain behaviour; Phase B. The contract it must satisfy is `ChainGateway` + SC-5/SC-6/SC-11. |
| `settlement_outbox` writer / unit of work | needs the session factory; Phase B, step 8. |
| Retry, backoff or re-signing logic | deliberately absent: SC-3/SC-6/SC-8 make a retry a contract violation, not a missing feature. |
| Database column names, indexes, ORM annotations | internal; hidden behind the repository ports (ADR-002). |
| Anchor batching policy | an open question in the module doc (ADR-006 default: batched; demo: per-envelope). Not a contract. |
| Sepolia confirmation count = 2 | proposed in the module doc's open questions; `ChainNetwork` carries whatever is chosen, so the freeze does not pin the number. |

Rejecting these is the point of a freeze: the failing tests are the specification, and each one maps to
an invariant in §1.

---

## 7. Amendment — the two-phase `ChainGateway` (closes B-1)

**Status:** Accepted by the re-freeze that implements the on-chain write path.
**Supersedes:** §2.8's `ChainGateway.submit(order) -> str`. Everything else in this file stands.

### 7.1 What changed

```python
# before — one call, hash only afterwards
class ChainGateway(Protocol):
    async def submit(self, order: SettlementOrder) -> str: ...

# after — two phases, the hash exists before anything is sent
@dataclass(frozen=True, slots=True)
class SignedPayment:
    tx_hash: str
    raw_transaction: str

class ChainGateway(Protocol):
    async def prepare(self, order: SettlementOrder) -> SignedPayment: ...
    async def broadcast(self, signed: SignedPayment) -> None: ...
```

Three supporting changes, each of which the split needs:

| Change | Why it is part of the same amendment |
|---|---|
| `SettlementStatus.SIGNED` (`"signed"`) | The state between "an order exists" and "the chain has it": the hash and the signed bytes are persisted, nothing has been broadcast. It is storable (`ck_settlement_orders_status`, migration `005_settlement_signed`) and reachable only through `SettlementOrder.mark_signed`. |
| `SettlementOrder.mark_signed(tx_hash, raw_transaction, signed_amount)` + `raw_transaction` on the order | SC-3 persists a *hash*; a hash without its bytes is a record an operator cannot act on. Storing the bytes makes recovery "re-send this", never "sign again" — the two are one transaction (one nonce), which is why a re-broadcast cannot pay twice. |
| `CommandAck.command_text` (additive, defaulted) | `command_ref` is the settlement command's identity and stays `payments.dispatch` (SC-2, and evidence keys on it). Since the amendment the governed step resolves that identity to `payments.broadcast --raw-tx <hex>`, so the audit record has to name the rendered text too. |

### 7.2 Why

`submit` signed **and** broadcast in one call, so the caller learned the hash only *after* the
transaction was on the wire. SC-3 requires the opposite order ("the caller has already persisted the hash
it is about to receive"), and no amount of application-layer care could restore it: the ordering was
unrepresentable in the port's shape. Faking a hash, or marking an order `SUBMITTED` without one, would
have destroyed the single ordering the commit-point lock depends on.

Signing is local — `eth_account` returns the signed bytes *and* their hash from the same call — so the
hash is available before anything is sent. That is why the port, not the wallet, was the blocker.

### 7.3 What it enables, in the contract's own terms

| Id | Now expressible as |
|---|---|
| **SC-3** | `prepare` → `mark_signed` (hash + bytes, status `signed`) → commit → governed broadcast → `mark_submitted`. The hash is durable before a node sees the bytes, and `SecondTransactionRefused` still refuses a second signature. |
| **SC-5** | Recovery re-broadcasts the persisted bytes, which is the same transaction; the on-chain nullifier remains the thing that refuses a second payment. |
| **SC-2** | Unchanged and stricter: the governed command is one module constant rendered from the order (`payments.broadcast --raw-tx {raw_transaction}`), and `payments.broadcast` accepts one option — it cannot look up an order, re-derive a network or sign. |
| **SC-6 / SC-7** | Untouched: a revert is still a refusal concluded once by `SettleOnce`, and finality is still a confirmation count. |

### 7.4 What is still *not* frozen

* **The broadcast transport.** That the governed step runs `payments.broadcast`, and that the binary
  sends bytes through `BURSAR_RPC_URL`, is an implementation decision recorded in the runbook — the
  contract fixes only that the command path is a module constant and that the bytes are already signed.
* **`ChainGateway.broadcast`'s caller.** The governed path broadcasts through Rigorix's `run_command`, so
  the port's in-process `broadcast` has no production caller today; it is the adapter-level form of the
  same single operation (same bytes, no new transaction) and is exercised by the chain suite. Wiring a
  second caller is a design change, not a refactor.
* **B-2 is still open.** `SettlementStatus.PENDING` / `ABANDONED` exist and the state diagram transitions
  into them, but `SettlementOrder` has no intention method for either, so `SettleOnce` cannot be written
  without a second amendment. An order therefore stops at `SUBMITTED`; nothing decides finality on the
  write path, and a receipt is read once after the broadcast as evidence only.
