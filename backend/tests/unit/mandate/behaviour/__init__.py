"""Behaviour tests for the Mandate domain — the traffic half of the acceptance criteria.

Canonical: docs/architecture/modules/mandate.md#acceptance-criteria
Reference: docs/architecture/modules/mandate.md#aggregate-payee

The `../<component>/` contract tests assert *shape* (signatures, immutability, layer purity) and stay
green as behaviour lands. These files assert *behaviour* — the numbered ACs of the module doc — using a
fake `OwnerSignatureProof` so no crypto is involved and every failure mode is reachable.
"""
