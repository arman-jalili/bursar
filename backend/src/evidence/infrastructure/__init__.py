"""Evidence infrastructure — adapters land in Phase B (frozen contract only).

Canonical: .pi/architecture/modules/evidence.md#architecture
Reference: docs/contracts/evidence-contract-freeze.md §5

The package exists so the DDD layer gate is satisfied and the dependency direction is explicit. It
contains **no adapter**: the HMAC signer, the SQLAlchemy envelope store, the Settlement anchor client
and migration `005_evidence` are Phase B, because a freeze that also writes persistence hides which
guarantees are still missing.

Frozen port shapes live in `src/evidence/domain/ports.py` and `src/evidence/domain/repositories.py`.
"""
