"""`PreconditionCheck` — the Lock-2 entrypoint (AC 11).

Canonical: docs/architecture/modules/authority.md#application-services
Reference: docs/contracts/authority-contract-freeze.md §2.9

It is deliberately **not** a sixth catalog service: it is the enforcement-shaped façade over
`EvaluateAuthority` + `ReserveCapacity`. Its contract is a status code, not a body convention:

    200  a decision was reached (`allow` or `escalate`)
    409  a documented refusal, with the determination's reason codes
    503  Mandate/Billing could not be read — **fail closed**, Rigorix must not run the command

The request carries the run-command parameters Rigorix already has (invoice, payee, amount). Routing
fields are rejected by the schema (A-2): the address and digest come from Mandate's verified record, read
now (A-6), and the amount becomes the intent's amount only because the enforcement client presents it as
the invoice amount — an *agent* cannot reach this endpoint, and the proposal path goes through Billing's
ACL port instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.authority.application.dto import DeterminationView, IntentView
from src.authority.application.services_impl import (
    AuthorityService,
    determination_view,
    intent_view,
)
from src.authority.domain.ports import InvoiceView
from src.authority.domain.values import Money
from src.authority.infrastructure.adapters import SqlMandateView
from src.shared.application.unit_of_work import session_scope

__all__ = ["PreconditionCheck", "PreconditionResult"]


@dataclass(frozen=True, slots=True)
class PreconditionResult:
    """The façade's answer. The router turns `decision` into a status code, never the reverse."""

    decision: str
    reason_codes: tuple[str, ...]
    determination_id: str
    intent: IntentView
    determination: DeterminationView


class PreconditionCheck(AuthorityService):
    """The enforcement-shaped façade: read Mandate now, decide, reserve — or fail closed."""

    async def execute(
        self,
        *,
        intent_id: str,
        invoice_id: str,
        payee_id: str,
        amount_micro_usdc: int,
    ) -> PreconditionResult:
        """Evaluate one presented payment.

        `intent_id` is the enforcement client's correlation id; the authoritative intent id is minted by
        the code-constructed intent and returned on the determination, so a refusal can still be traced.
        """
        async with session_scope(self._factory) as session:
            mandate = SqlMandateView(session)
            # A-6: the household comes from the payee record, read now — the request does not name it.
            household_id = await mandate.household_of(payee_id)
            invoice = InvoiceView(
                invoice_id=invoice_id, payee_id=payee_id, amount=Money(amount_micro_usdc)
            )
            intent, determination, _ = await self._evaluate(
                session, invoice=invoice, household_id=household_id
            )
        view = determination_view(determination)
        return PreconditionResult(
            decision=determination.verdict.value,
            reason_codes=view.reason_codes,
            determination_id=determination.id,
            intent=intent_view(intent),
            determination=view,
        )
