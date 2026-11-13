"""Evidence — the capture-and-verify context (frozen contract).

Canonical: .pi/architecture/modules/evidence.md
Reference: docs/contracts/evidence-contract-freeze.md

Evidence is a **witness, not a guard**: it seals every domain fact into a signed envelope and
anchors the envelope hash, but it never blocks a payment. Phase A contains signatures only — every
body raises `NotImplementedError("E-n — see module doc")` until Phase B.
"""
