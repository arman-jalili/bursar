"""Evidence infrastructure — the adapters behind the frozen ports.

Canonical: docs/architecture/modules/evidence.md#architecture
Reference: docs/contracts/evidence-contract-freeze.md §2.5, §2.6

    signer.py          HMAC-SHA256; the only holder of the operator key (E-9)
    models.py          SQLAlchemy rows for `evidence_*`
    repositories.py    append-only envelope/anchor stores + the idempotency claim (E-4, E-5, E-8)
    mappers.py         row ⇄ envelope/anchor translation; UTC normalisation for canonical bytes
    anchor.py          local anchor gateway (Settlement owns the production write) + policy
    expected_events.py publisher-outbox read model for the witness-gap report (E-10)

Nothing here is imported by `domain/` or `application/services.py`; the composition root and the
concrete application wrappers are the only seams that know adapters exist.
"""
