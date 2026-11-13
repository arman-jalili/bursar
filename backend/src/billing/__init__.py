"""Billing — invoices, payment attempts, and the agent's only legal output.

Canonical: .pi/architecture/modules/billing.md
Reference: docs/contracts/billing-contract-freeze.md

**Phase A: contract freeze.** This package contains signatures and the refusal vocabulary only; every
body raises `NotImplementedError("B-n — see module doc")`. Nothing here decides whether a payment may
move — that is Authority's job (see the context map). Billing's job is to make proposals **untrusted,
structured and non-duplicable** before they reach Authority.

The frozen surface, and nothing else:

    domain/values.py           InvoiceHash · BilledAmount · InvoiceStatus · AttemptStatus
    domain/errors.py           BillingRefusal · DuplicateInvoice · InvoiceNotPayable ...
    domain/invoice.py          Invoice                     (B-1 … B-4)
    domain/payment_attempt.py  PaymentAttempt · FORBIDDEN_PROPOSAL_KEYS   (B-5 … B-7)
    domain/repositories.py     InvoiceRepository · PaymentAttemptRepository
    application/services.py    RecordInvoice · ProposePayment (the catalog names)
    application/dto.py         commands and results for those two services

Absent on purpose: `infrastructure/`, `interfaces/`. A freeze that also ships adapters is not a freeze.
"""

__contract_version__ = "1.0.0"
