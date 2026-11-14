"""Evidence interfaces — HTTP contract frozen, handlers land in Phase B.

Canonical: docs/architecture/modules/evidence.md#api-endpoints
Reference: docs/contracts/evidence-contract-freeze.md §2.8

Route handlers are **concrete** and do not get a second interface file: `interfaces/http/` will hold a
router and Pydantic schemas in Phase B. The frozen part is the endpoint shape the console is built
against:

    GET /v1/evidence                 list envelopes (no payload unless ?full=1)
    GET /v1/evidence/{id}            envelope + hmac + anchor
    GET /v1/evidence/{id}/verify     {result, field?, anchor_tx} · 409 on mismatch
    GET /v1/evidence/{id}/anchor     anchor tx, block, chain id

Registration in the app shell is the runtime-integration item, not part of this freeze.
"""
