"""Settlement — move USDC and prove it happened exactly once.

Canonical: .pi/architecture/modules/settlement.md
Reference: docs/contracts/settlement-contract-freeze.md

**Phase A: contract freeze.** This package contains signatures and the refusal vocabulary only; every
body raises `NotImplementedError("SC-n — see module doc")`. The only body that does anything is
`domain.ids.new_id()`, because identifier generation is not behaviour and stubbing it would force every
test to invent ids.

Settlement is Lock 3 — the commit-point lock. Even a stolen operator key cannot make it pay a payee the
contract rejects, exceed the signed amount, or pay the same invoice twice, because the refusal happens
inside the transaction. The frozen surface is the smallest one that keeps that claim checkable:

    domain/values.py            Nullifier · ChainNetwork · SettlementStatus · ReceiptStatus
    domain/views.py             PaymentIntentView · DeterminationView   (the ACL inputs)
    domain/errors.py            SettlementRefusal · DispatchWithoutAuthority · DuplicateSettlementBlocked ...
    domain/settlement_order.py  SettlementOrder · PAYMENT_COMMAND        (SC-1 … SC-6, SC-9)
    domain/chain_receipt.py     ChainReceipt                            (SC-7, SC-10)
    domain/services.py          NullifierPolicy · FinalityPolicy
    domain/repositories.py      SettlementOrderRepository · NullifierRepository · ChainReceiptRepository
    domain/ports.py             PaymentExecutor · ChainGateway · DeterminationGate
    application/services.py     DispatchPayment · SettleOnce · GetReceipt · ListOrders · AnchorHash · CostSummary
    application/dto.py          commands and results for those six

Absent on purpose: adapters, routers, migrations, `PaymentRouter.sol`. A freeze that also ships adapters
is not a freeze — it hides which guarantees are still missing.
"""

__contract_version__ = "1.0.0"
