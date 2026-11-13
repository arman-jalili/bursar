"""Authority — the decision engine: intents, determinations, the cap ledger and approvals.

Canonical: .pi/architecture/modules/authority.md
Reference: docs/contracts/authority-contract-freeze.md

**Phase A: contract freeze.** Signatures and the refusal vocabulary only; every body raises
`NotImplementedError("A-n — see module doc")`. The one exception is `new_id()`, which returns a uuid.

This is the system's heart, and the only context allowed to answer *"may this payment move?"*. Three
things make that answer trustworthy, and each is an invariant below:

    1. the decision is taken against the rules **re-read at the moment of consequence** (A-6)
    2. the cap is reserved **atomically**, so six split invoices cannot jointly overdraw it (A-9)
    3. an escalation is bound to **one exact intent**, single-use and expiring (A-13…A-15)

Absent on purpose: adapter and router bodies. `infrastructure/` and `interfaces/` exist as empty
packages so the layer structure is complete, but they contain no SQLAlchemy models, no client, no
router and no EIP-712 signer implementation — those are Phase B. The event payloads
(`domain/events.py`) and the HTTP contract (freeze doc §2.9) *are* frozen here, because downstream
contexts must be able to build against them before Authority can enforce anything.
"""

__contract_version__ = "1.0.0"
