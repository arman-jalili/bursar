"""Evidence interfaces — concrete handlers for the frozen HTTP shape.

Canonical: docs/architecture/modules/evidence.md#api-endpoints
Reference: docs/contracts/evidence-contract-freeze.md §2.9

Route handlers are **concrete** and have no second interface file. The endpoint shape is frozen:

    GET /v1/evidence                 list envelopes (no payload unless ?full=1)
    GET /v1/evidence/{id}            envelope + hmac + anchor
    GET /v1/evidence/{id}/verify     {result, field?, anchor_tx} · 409 on mismatch
    GET /v1/evidence/{id}/anchor     anchor tx, block, chain id

`subscriber.py` is the runtime entry path for sealing: the publisher-outbox worker hands it one
`DomainEvent` and it returns a `SealEvidenceResult`. Registration in the app shell is the
composition root's job.
"""
