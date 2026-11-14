"""Billing application layer — use cases, DTOs, and the unit-of-work boundary.

Canonical: docs/architecture/modules/billing.md#application-services
Reference: docs/contracts/billing-contract-freeze.md §2.7

Phase A: signatures only. `RecordInvoice` and `ProposePayment` are ABCs whose `execute` raises
`NotImplementedError("B-n — see module doc")`.

What the implementations will own (and the domain will not): exactly one `session_scope` per use case,
the `DuplicateInvoice`/`InvoiceNotPayable` guards being *called* rather than re-implemented, and the
outbox append in the same transaction.
"""
