"""Evidence — the capture-and-verify context.

Canonical: docs/architecture/modules/evidence.md
Reference: docs/contracts/evidence-contract-freeze.md

Evidence is a **witness, not a guard**: it seals every domain fact into a signed envelope and
anchors the envelope hash, but it never blocks a payment. A signing or anchoring outage becomes a
visible witness gap (`WitnessReport`), never a publisher error (E-10).

Layers: `domain/` is framework-free; `application/` owns the unit of work; `infrastructure/` holds
the HMAC signer, SQLAlchemy stores and the anchor gateway; `interfaces/` holds the concrete HTTP
router and the event subscriber.
"""
