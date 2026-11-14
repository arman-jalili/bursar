# Console — Contract Freeze (Phase A)

**Module:** Console (generic subdomain, adapter depth — ADR-008)
**Status:** Frozen for implementation — 2026-11-13
**Canonical module doc:** [`docs/architecture/modules/console.md`](../../../docs/architecture/modules/console.md)
**Depends on:** Authority (frozen at `e4a815f`) · Billing (frozen at `466b923`) · Mandate (implemented) ·
Evidence (contract pending) · Settlement (contract pending)
**Decisions:** [ADR-001](../../../docs/architecture/decisions/ADR-001-architecture-pattern.md),
[ADR-004](../../../docs/architecture/decisions/ADR-004-api-design.md),
[ADR-005](../../../docs/architecture/decisions/ADR-005-authentication-authorization.md),
[ADR-007](../../../docs/architecture/decisions/ADR-007-compliance-engine-architecture.md) ·
ADR-008 (modeling depth — no decision record file; see the module doc's §Modeling Depth Note)

---

## 1. What is frozen, and what is not

Frozen: **the read-model DTOs, the six upstream ports, the read-model cache port, the three
catalogued projections, the surface whitelists, the refusal vocabulary and its copy table, the
eight HTTP routes, and the invariant ids `CON-01 … CON-10`.** Every behaviour body is
`raise NotImplementedError("CON-n — see module doc")`, so the module cannot do anything yet — by
design.

Not frozen (Phase B, implementation): behaviour bodies, the FastAPI router, the HTTP adapter
internals (timeouts, retries, auth headers), the in-process TTL cache implementation, and the
React/TS/Vite app. Phase A deliberately ships **no** adapter implementation: a contract freeze that
also writes HTTP plumbing hides which guarantees are still missing.

**One thing is frozen by absence:** there is no `src/console/domain/` package and there will never
be one (CON-09). The console is the one context where "no model" is the correct model.

**Ten invariants. A test that does not defend one of them does not belong in this suite.**

| Id | Invariant (rule) | Illegal state prevented | Defending suite |
|---|---|---|---|
| **CON-01** | An upstream payload reaches a console surface **only through a surface whitelist**; a key the whitelist does not name is dropped, never forwarded. | A new upstream field (`internal_note`, an agent guess) appearing in a screen and being read as fact. | `tests/unit/console/whitelist/`, `tests/unit/console/anti-corruption-layer-field-whitelists/` |
| **CON-02** | `payee_address` and `bank_digest` are rendered **byte-identically** to Authority's intent: no truncation, no lowercasing, no re-checksumming, no float round-trip on amounts. | The owner approving a string that does not match the fields the signature binds. | `tests/unit/console/exact-fields/`, `tests/unit/console/ports-upstream-clients/` |
| **CON-03** | `POST /v1/console/approvals/{id}/signature` **forwards the received body unmodified**; the console constructs, defaults, re-orders and rewrites nothing. | The console silently repairing a signature and becoming a signing authority. | `tests/unit/console/passthrough/` |
| **CON-04** | The console owns **exactly one write** — the signature passthrough. No endpoint or port may create an intent, attempt or settlement order. | Console-scope escalation: the owner token reaching the paths that move money. | `tests/unit/console/read-only/`, `tests/unit/console/ports-upstream-clients/` |
| **CON-05** | Payer-facing copy contains **none of** `USDC`, `gas`, `chain`, `wallet`, `nullifier`, `determination`. | Crypto vocabulary on a household payer screen (NFR-017). | `tests/unit/console/payer-copy/` |
| **CON-06** | Every payer bill backed by a settlement carries `payout_simulated: true` **and** the demo label. | A demo bill presented as a real bank transfer. | `tests/unit/console/simulated-payout/` |
| **CON-07** | A refused payment is shown to the owner with a **human-readable reason derived from the closed reason-code set** — never the raw code. | A refusal the owner cannot act on (scenarios 2/3/4). | `tests/unit/console/refusal-reason/` |
| **CON-08** | The evidence view reports `verified` for an untouched envelope and `tampered` after a single byte changes; the verdict is **Evidence's, proxied**. | The console computing its own verification opinion (a second, weaker witness). | `tests/unit/console/verify-toggle/` |
| **CON-09** | `src/console/domain/` **does not exist**; the console has no domain layer. | Business rules hiding in the generic subdomain (ADR-008). | `tests/unit/console/no-domain-layer/` |
| **CON-10** | Both surfaces are usable at **390×844** with no horizontal scroll; owner approval takes **≤3 taps** from the notification (NFR-011). | A phone-only demo that quietly requires a desktop. | `tests/unit/console/mobile/` |

### 1.1 Why these ten and not the module's feature list

Every row is a **negative** guarantee: something the console must never do. Positive features
(render a list, show a page) fail by being absent and are covered by integration tests once the
router exists. The rows above fail by being *present and wrong*, which is the failure mode the freeze
exists to catch. `CON-04` and `CON-09` are the two that would pass a demo and destroy the safety
claim.

---

## 2. Frozen signatures — `src/console/`

### 2.1 Read models — `application/dto.py`

These are **DTOs, not entities** (module doc §Entity Relationship): no identity, no lifecycle, no
invariants. Two identical `PaymentReadModel` instances are interchangeable.

```python
@dataclass(frozen=True, slots=True)
class ApprovalInboxItem:
    approval_id: str
    intent_id: str
    invoice_id: str
    payee_name: str
    payee_address: str  # byte-identical to Authority's intent (CON-02)
    amount_usdc: str  # exact decimal string — never float/Decimal-rendered (CON-02)
    bank_digest: str  # byte-identical to Authority's intent (CON-02)
    is_new_payee: bool
    requires_owner_signature: bool
    reason_codes: tuple[str, ...]
    expires_at: datetime
    typed_data_hash: str  # owner surface only — never on a payer bill (CON-01)


class BillStatus(StrEnum):
    RECEIVED | IN_FLIGHT | SETTLED | REFUSED


@dataclass(frozen=True, slots=True)
class PaymentReadModel:
    invoice_id: str
    payee_name: str
    amount_usdc: str
    status: BillStatus
    status_plain: str  # household language (CON-05)
    settled_at: datetime | None
    tx_hash: str | None  # shown only in the owner evidence view, not the payer list
    payout_simulated: bool
    payout_label: str | None  # CON-06 demo label, travels with the bill
    refusal_reason: str | None  # CON-07 household reason, never the raw code


@dataclass(frozen=True, slots=True)
class EvidenceReadModel:
    envelope_id: str
    event_type: str
    occurred_at: datetime
    result: str
    anchor_tx: str | None


class VerificationOutcome(StrEnum):
    VERIFIED | TAMPERED | UNKNOWN


@dataclass(frozen=True, slots=True)
class VerificationReadModel:
    envelope_id: str
    outcome: VerificationOutcome
    checked_at: datetime
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PayeeReadModel:
    payee_id: str
    display_name: str
    status: str
    status_plain: str


@dataclass(frozen=True, slots=True)
class ConstitutionReadModel:
    version: str
    cap_usdc: str
    threshold_usdc: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class SignatureSubmission:
    approval_id: str
    raw_body: bytes  # the bytes as received (CON-03)
    content_type: str
    owner_scope: str


@dataclass(frozen=True, slots=True)
class SignatureOutcome:
    granted: bool
    reason_plain: str | None  # CON-07
    reason_codes: tuple[DenialReasonCode, ...]


class Surface(StrEnum):
    OWNER_INBOX | PAYER_BILL | PAYEE_LIST | CONSTITUTION | EVIDENCE | VERIFICATION
```

**`amount_usdc` is a `str` on purpose.** `320.00` through a float is `319.99999999999994`; through
`Decimal` it is exact but its renderer is a formatting decision the console is not allowed to make
(CON-02). The string Authority produced is the string the owner sees.

`tx_hash` exists on the payer model because Settlement supplies it, but the payer *renderer* must
not show it — vocabulary is enforced on copy (CON-05), not by dropping the field and re-fetching it
from another source.

### 2.2 Presentation contract — `application/presentation.py`

```python
PAYER_STATUS_COPY: Final[Mapping[BillStatus, str]] = {
    RECEIVED: "Bill received",
    IN_FLIGHT: "Being paid",
    SETTLED: "Paid",
    REFUSED: "Paused",
}
PAYER_FORBIDDEN_TERMS: Final[tuple[str, ...]] = (
    "usdc",
    "gas",
    "chain",
    "wallet",
    "nullifier",
    "determination",
)
PAYOUT_SIMULATED_LABEL: Final[str] = "bank transfer simulated in this demo"


def payer_status_copy(status: BillStatus, *, payout_simulated: bool) -> str: ...  # CON-05
def payout_label(payout_simulated: bool) -> str: ...  # CON-06


@dataclass(frozen=True, slots=True)
class Viewport:
    width_px: int
    height_px: int


MOBILE_VIEWPORT: Final[Viewport] = Viewport(width_px=390, height_px=844)  # CON-10
MAX_APPROVAL_TAPS: Final[int] = 3  # CON-10


def assert_mobile_contract(viewport: Viewport = MOBILE_VIEWPORT) -> None: ...  # CON-10
```

The status→copy table is a **lookup, not a Strategy** (module doc §Patterns): six strings do not
justify a class hierarchy. It is frozen as data so a copy change is a contract change and shows up
in review.

### 2.3 Refusal vocabulary — `application/refusals.py`

The console **translates** Authority's closed `DenialReason` set; it does not extend it. A code that
Authority does not emit cannot exist here, and a code Authority emits without copy cannot be
rendered (that is the failure CON-07 exists to prevent).

```python
class DenialReasonCode(StrEnum):
    DIGEST_MISMATCH | PAYEE_QUARANTINED | PAYEE_FROZEN | CAP_EXCEEDED |
    DUPLICATE_INVOICE | APPROVAL_INVALID | BUDGET_EXHAUSTED | AMOUNT_MISMATCH

REFUSAL_COPY: Final[Mapping[DenialReasonCode, str]] = {
    DIGEST_MISMATCH:    "Blocked: the bank details didn't match",
    PAYEE_QUARANTINED:  "Paused while we check this payee",
    PAYEE_FROZEN:       "Paused by the owner",
    CAP_EXCEEDED:       "Paused: this month's limit was reached",
    DUPLICATE_INVOICE:  "This bill was already handled",
    APPROVAL_INVALID:   "The approval didn't match this payment",
    BUDGET_EXHAUSTED:   "Paused: this month's budget is used up",
    AMOUNT_MISMATCH:    "Blocked: the amount didn't match the bill",
}

def refusal_copy(codes: Iterable[DenialReasonCode]) -> str: ...  # CON-07
```

Rules encoded by the signature rather than by convention:

* `refusal_copy` takes the **closed enum**, not `Iterable[str]`. A raw upstream string cannot reach
  the renderer, so an unknown code fails at the boundary instead of printing `DIGEST_MISMATCH` at a
  household.
* An empty iterable is a refusal with no reason → raises `RefusalReasonMissing`, never a generic
  "Payment failed".

### 2.4 Console refusals — `application/errors.py`

These are **presentation refusals**, not domain errors: the console has no domain (CON-09). They are
the vocabulary an implementation raises and a test asserts; the HTTP layer maps them to the shared
error envelope (ADR-004).

```python
class ConsoleRefusal(Exception):            # base — every console refusal derives from it
class WhitelistViolation(ConsoleRefusal)    # CON-01
class FieldFidelityViolation(ConsoleRefusal)# CON-02
class SignatureRewritten(ConsoleRefusal)    # CON-03
class ReadOnlyViolation(ConsoleRefusal)     # CON-04
class PayerVocabularyViolation(ConsoleRefusal)  # CON-05
class PayoutNotLabelled(ConsoleRefusal)     # CON-06
class RefusalReasonMissing(ConsoleRefusal)  # CON-07
class UnknownReasonCode(ConsoleRefusal)     # CON-07
class VerificationRefused(ConsoleRefusal)   # CON-08
class DomainLayerPresent(ConsoleRefusal)    # CON-09
class ViewportContractViolation(ConsoleRefusal)  # CON-10
```

### 2.5 Upstream ports — `application/ports.py`

Ports return **raw upstream mappings**. Narrowing is the ACL's job (CON-01), so a port that returned
a typed DTO would put the whitelist behind whichever adapter happened to build it.

```python
class ApprovalInboxPort(Protocol):
    async def list_pending(
        self, owner_scope: str
    ) -> tuple[Mapping[str, object], ...]: ...  # CON-01
    async def submit_signature(
        self, approval_id: str, raw_body: bytes, content_type: str
    ) -> Mapping[str, object]: ...  # CON-03


class DeterminationPort(Protocol):
    async def reasons_for(self, intent_id: str) -> tuple[str, ...]: ...  # CON-07


class BillsPort(Protocol):
    async def list_invoices(self, scope: str) -> tuple[Mapping[str, object], ...]: ...  # CON-01
    async def get_invoice(self, invoice_id: str) -> Mapping[str, object]: ...  # CON-02


class ReceiptPort(Protocol):
    async def receipt_for(self, invoice_id: str) -> Mapping[str, object] | None: ...  # CON-06


class EvidencePort(Protocol):
    async def list_envelopes(
        self, intent_id: str | None
    ) -> tuple[Mapping[str, object], ...]: ...  # CON-01
    async def verify(self, envelope_id: str) -> Mapping[str, object]: ...  # CON-08


class ConstitutionPort(Protocol):
    async def current(self) -> Mapping[str, object]: ...  # CON-01
    async def payees(self) -> tuple[Mapping[str, object], ...]: ...  # CON-01
```

There is **no** `IntentPort`, `AttemptPort`, `DispatchPort` or `SettlementPort`. Their absence is
CON-04: a console that cannot name the operation cannot call it. The only write-shaped method on any
port is `submit_signature`, and its parameter is `bytes`, not a parsed model — there is nothing for
the console to normalise.

### 2.6 Read-model cache port — `infrastructure/repository/cache.py`

```python
class ReadModelCache(Protocol):
    def get(self, key: str) -> Mapping[str, object] | None: ...  # CON-02
    def put(self, key: str, value: Mapping[str, object], ttl_seconds: int) -> None: ...  # CON-02
    def invalidate(self, key: str) -> None: ...  # CON-02
```

**No `clear()`, no iteration, no `commit()`.** A cache the console can enumerate is a second store
of upstream truth; the TTL is the only expiry rule. Caching a *projected* view is allowed; caching
a raw upstream payload and re-projecting on read is not, because the whitelist would then be applied
to a stale shape.

### 2.7 Projections — `application/services.py`

The three catalogued names from the module doc. `ProjectApprovalInbox` also serves the two owner
display reads (payees, constitution): the module doc names three projections, and a fourth class for
two lookup tables would be ceremony.

```python
class ProjectApprovalInbox:
    def __init__(
        self,
        approvals: ApprovalInboxPort,
        determinations: DeterminationPort,
        constitution: ConstitutionPort,
    ) -> None: ...
    async def execute(self, owner_scope: str) -> tuple[ApprovalInboxItem, ...]: ...  # CON-02
    async def payees(self, owner_scope: str) -> tuple[PayeeReadModel, ...]: ...  # CON-01
    async def constitution_version(self, owner_scope: str) -> ConstitutionReadModel: ...  # CON-01


class ProjectPayerBills:
    def __init__(self, bills: BillsPort, receipts: ReceiptPort) -> None: ...
    async def execute(self, scope: str) -> tuple[PaymentReadModel, ...]: ...  # CON-06
    async def one(self, scope: str, invoice_id: str) -> PaymentReadModel: ...  # CON-06


class ProjectEvidence:
    def __init__(self, evidence: EvidencePort) -> None: ...
    async def envelopes(self, intent_id: str | None) -> tuple[EvidenceReadModel, ...]: ...  # CON-01
    async def verify(self, envelope_id: str) -> VerificationReadModel: ...  # CON-08
```

No projection takes a `Session`, a repository or a database handle. The console reads other
contexts through their ports (module doc §Ports); a local table would make it a writer.

### 2.8 Surface whitelists — `infrastructure/acl.py`

```python
OWNER_INBOX_FIELDS = (
    "approval_id",
    "intent_id",
    "invoice_id",
    "payee_name",
    "payee_address",
    "amount_usdc",
    "bank_digest",
    "is_new_payee",
    "requires_owner_signature",
    "reason_codes",
    "expires_at",
    "typed_data_hash",
)
PAYER_BILL_FIELDS = (
    "invoice_id",
    "payee_name",
    "amount_usdc",
    "status",
    "settled_at",
    "tx_hash",
    "payout_simulated",
)
PAYEE_FIELDS = ("payee_id", "display_name", "status")
CONSTITUTION_FIELDS = ("version", "cap_usdc", "threshold_usdc", "published_at")
EVIDENCE_FIELDS = ("envelope_id", "event_type", "occurred_at", "result", "anchor_tx")
VERIFICATION_FIELDS = ("envelope_id", "outcome", "checked_at", "detail")
FORBIDDEN_UPSTREAM_KEYS = ("internal_note", "agent_guess", "confidence", "reasoning", "raw_payload")


def project_owner_inbox(upstream: Mapping[str, object]) -> dict[str, object]: ...  # CON-01
def project_payer_bill(upstream: Mapping[str, object]) -> dict[str, object]: ...  # CON-01
def project_payee(upstream: Mapping[str, object]) -> dict[str, object]: ...  # CON-01
def project_constitution(upstream: Mapping[str, object]) -> dict[str, object]: ...  # CON-01
def project_evidence(upstream: Mapping[str, object]) -> dict[str, object]: ...  # CON-01
def project_verification(upstream: Mapping[str, object]) -> dict[str, object]: ...  # CON-08
```

* Each surface has its **own** tuple. There is no shared "pass everything" projection, and no
  `project_all` helper: the whitelist is the door, so a convenience wrapper would be a second door.
* `FORBIDDEN_UPSTREAM_KEYS` is explicit so a projection can *refuse* (raise `WhitelistViolation`)
  rather than silently drop a key that looks like model output. A silent drop is indistinguishable
  from a typo; a raise names the field in review. (`CON-01` allows either at the boundary; the frozen
  behaviour is raise, and the test asserts the call fails until Phase B decides.)
* `PAYER_BILL_FIELDS` deliberately excludes `typed_data_hash` and `bank_digest`. `CON-01` is about
  audience separation, not only about unknown keys.

### 2.9 HTTP adapters — `infrastructure/http.py`

```python
@dataclass(frozen=True, slots=True)
class HttpAdapterConfig:
    base_url: str
    timeout_seconds: float = 2.0


class AuthorityHttpAdapter(ApprovalInboxPort, DeterminationPort): ...  # CON-01, CON-03, CON-07


class BillingHttpAdapter(BillsPort): ...  # CON-01, CON-02


class SettlementHttpAdapter(ReceiptPort): ...  # CON-06


class EvidenceHttpAdapter(EvidencePort): ...  # CON-08


class MandateHttpAdapter(ConstitutionPort): ...  # CON-01
```

Adapters inherit the ports so mypy fails a client that drifts from the frozen surface. They own
transport only: URL, timeout, auth header, JSON decode — never a field rename (CON-02) and never a
verdict (CON-08). No adapter has a `post`/`send`/`create` method other than
`AuthorityHttpAdapter.submit_signature`.

### 2.10 Layer purity — `infrastructure/purity.py`

```python
FORBIDDEN_LAYERS: Final[tuple[str, ...]] = ("domain",)


def declared_layers() -> tuple[str, ...]: ...  # CON-09
```

`declared_layers()` is the seam the architecture tests call. It is frozen here so
the gate and the implementation cannot disagree about which layers exist.

### 2.11 HTTP surface — `interfaces/api.py`

```python
@dataclass(frozen=True, slots=True)
class Route:
    method: str
    path: str
    scope: str
    mutating: bool = False
    handler: str = ""

@dataclass(frozen=True, slots=True)
class ConsoleDeps:
    approval_inbox: ProjectApprovalInbox
    payer_bills: ProjectPayerBills
    evidence: ProjectEvidence

SIGNATURE_PATH: Final[str] = "/v1/console/approvals/{id}/signature"
CONSOLE_ROUTES: Final[tuple[Route, ...]] = ( ... eight rows, §2.12 ... )

def build_router(deps: ConsoleDeps) -> object: ...                     # CON-04
async def approval_inbox(deps, owner_scope) -> tuple[ApprovalInboxItem, ...]: ...  # CON-01
async def submit_signature(deps, approval_id, raw_body, content_type, owner_scope) -> SignatureOutcome: ...  # CON-03
async def payer_bills(deps, scope) -> tuple[PaymentReadModel, ...]: ...            # CON-06
async def payer_bill(deps, scope, invoice_id) -> PaymentReadModel: ...             # CON-06
async def payee_list(deps, owner_scope) -> tuple[PayeeReadModel, ...]: ...         # CON-01
async def constitution(deps, owner_scope) -> ConstitutionReadModel: ...           # CON-01
async def evidence_list(deps, owner_scope, intent_id) -> tuple[EvidenceReadModel, ...]: ...  # CON-01
async def verify(deps, owner_scope, envelope_id) -> VerificationReadModel: ...      # CON-08
```

Routers are concrete (issue note); there is no `RouterPort`. `CONSOLE_ROUTES` is frozen data because
it is the contract the React app and the auth matrix are built against before the router exists.

### 2.12 The eight routes, frozen

| Method | Path | Scope | Mutating | Handler |
|---|---|---|---|---|
| GET | `/v1/console/approvals` | `authority:read` | no | `approval_inbox` |
| POST | `/v1/console/approvals/{id}/signature` | `authority:sign` | **yes** | `submit_signature` |
| GET | `/v1/console/bills` | `console:read` | no | `payer_bills` |
| GET | `/v1/console/bills/{invoice_id}` | `console:read` | no | `payer_bill` |
| GET | `/v1/console/payees` | `console:read` | no | `payee_list` |
| GET | `/v1/console/constitution` | `console:read` | no | `constitution` |
| GET | `/v1/console/evidence` | `evidence:read` | no | `evidence_list` |
| GET | `/v1/console/evidence/{id}/verify` | `console:read` | no | `verify` |

Exactly one `mutating=True` row. There is no `POST /v1/console/intents`, no
`POST /v1/console/attempts`, no `POST /v1/console/settlements` — and their absence is asserted, not
assumed (CON-04).

---

## 3. Ordered Phase-B work list

Each step is a PR that depends on the frozen signatures above and on the previous step. The order is
the module doc's implementation sequence, made explicit about what proves each step done. Steps 1–2
are deliberately the surfaces with no signing path: a read-only bug cannot move money.

| # | Work | Depends on | Done when | Defends |
|---|---|---|---|---|
| B1 | ACL whitelists + plain-language tables (`project_*`, `PAYER_STATUS_COPY`, `REFUSAL_COPY`) | — | `tests/unit/console/whitelist/`, `.../payer-copy/`, `.../refusal-reason/` green | CON-01, CON-05, CON-07 |
| B2 | `ProjectPayerBills` (read-only, no signing dependency) | B1, Billing frozen | payer bills return household language; settled bills carry the demo label | CON-06 |
| B3 | `ProjectApprovalInbox` with exact intent fields + `typed_data_hash` | B1, Authority frozen | `payee_address`/`bank_digest` byte-identical to the intent; `tests/.../exact-fields/` green | CON-02 |
| B4 | Signature passthrough endpoint + rejection copy | B3, ADR-005 scopes | recorded request body equals received body; wrong scope is 403 | CON-03, CON-07 |
| B5 | `ProjectEvidence` + verification proxy + verified/tampered toggle | B1, Evidence frozen | scenario 7: untouched → `verified`, one byte flipped → `tampered` | CON-08 |
| B6 | FastAPI router from `CONSOLE_ROUTES`; auth matrix per scope | B2–B5 | owner token cannot reach a creating path; `tests/.../read-only/` green | CON-04 |
| B7 | Adapter-purity gate wiring (`declared_layers`) | B1 | `src/console/domain/` absent and the gate fails if it appears | CON-09 |
| B8 | React/TS/Vite surfaces; empty/loading/error states; mobile viewport pass | B2–B6 | 390×844 with no horizontal scroll; approval ≤3 taps | CON-10 |
| B9 | OpenAPI export for the eight routes (ADR-004, hour 6) | B6 | React team codes against committed schema | CON-04 |

Steps B1–B2 can start as soon as this freeze merges. B5 and the payer receipt path are **blocked on
the Evidence and Settlement contract freezes** — the ports are frozen here, but an integration test
cannot assert a proxied verdict against an unfrozen upstream.

---

## 4. Explicitly out of scope

| Out of scope | Why | Where it belongs instead |
|---|---|---|
| `src/console/domain/` — entities, aggregates, value objects, domain services | The console is a generic subdomain modelled at adapter depth (ADR-008). Its absence is CON-09. | Nowhere. Introducing it is an architecture violation, not a refactor. |
| Creating intents, attempts or settlement orders | Console is the edge; it cannot trigger a payment (module doc §Description, CON-04). | Authority / Settlement. |
| Decision logic: allow/deny, cap arithmetic, payee eligibility | Rules live in Authority / Mandate (principle 7). The console renders verdicts. | Authority, Mandate. |
| EIP-712 signing, recovery and verification | The wallet signs; Evidence verifies; the console forwards bytes (CON-03). | Wallet (client), Evidence. |
| Database schema, SQLAlchemy models, migrations, outbox | The console owns no tables. | Each owning context. |
| HMAC envelope format, anchoring, chain interaction | Evidence / Settlement. | Evidence, Settlement. |
| Authentication implementation (token issuance, scopes) | ADR-005 owns scopes; the console only declares the scope required per route. | ADR-005 / platform auth. |
| React component internals, styling, design system | The freeze covers the API and copy contract the UI consumes. | Frontend epic. |
| Retry/backoff/timeout policy of the upstream adapters | Transport detail behind a frozen port. | Infrastructure adapter PR (B4/B5). |
| Refusal codes not emitted by Authority | The console translates a closed set (CON-07); it does not invent codes. | Authority (`DenialReason`). |

---

## 5. What would break this freeze

* Adding a field to a screen without adding it to that surface's whitelist tuple (CON-01).
* Letting the UI format `payee_address`, `bank_digest` or `amount_usdc` (CON-02).
* Parsing and rebuilding the signature body — even "to add the approval id" (CON-03).
* Adding a port method that creates or dispatches (CON-04).
* Softening a refusal into "Payment failed" or printing a raw code (CON-07).
* Computing verification in the console instead of proxying Evidence (CON-08).
* Creating `src/console/domain/` for "just one value object" (CON-09).

Any of these is a **contract change**: stop, ask the human to unfreeze, re-run Phase A, merge, then
record. An implementation PR may not amend this file.
