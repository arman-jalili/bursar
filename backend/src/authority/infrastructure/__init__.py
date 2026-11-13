"""Authority infrastructure — adapters for the frozen domain ports (Phase B).

Canonical: .pi/architecture/modules/authority.md#architecture
Reference: docs/contracts/authority-contract-freeze.md §5

Empty on purpose in Phase A. A freeze that also writes persistence hides which guarantees are still
missing; the conditional-`UPDATE` ledger adapter, the `authority_outbox` writer, the `MandateView`
read-through client and migration `003_authority` arrive with their own items.

What will live here, and nothing else:

    repository/     SQLAlchemy implementations of `domain/repositories.py`; `try_reserve_atomic`
                    is one `UPDATE ... WHERE committed + reserved + :amount <= cap`, never
                    read-then-write (A-9)
    adapters/       `MandateView` → Mandate HTTP client, read-through with no cache (A-6)
    outbox/         `authority_outbox` append, in the caller's transaction (ADR-003)

No port exposes transaction control, and the arrows point inward: infrastructure imports domain,
never the reverse.
"""

__all__: list[str] = []
