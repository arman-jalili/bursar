"""SC-2 — the dispatch command path is a module constant, not an input.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-2)
Reference: .pi/architecture/modules/settlement.md#components

Defends module AC #2: `command_params()` returns `payments.dispatch`, and a caller supplying a path is
impossible — `command_ref` is a ClassVar, so there is no constructor argument and no instance field to
taint. Rejecting a caller-supplied path matters more than validating one: a validated path is still a
path an injection can aim at the wrong payee.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.settlement_order import PAYMENT_COMMAND, SettlementOrder
from src.settlement.domain.values import SettlementStatus
from src.shared.domain.money import Money


class TestCommandParams:
    def test_the_path_is_the_module_constant(self, order) -> None:
        """SC-2 / AC-2: the only command that can be generated is `payments.dispatch`."""
        assert order.command_params()["command"] == PAYMENT_COMMAND

    def test_a_caller_supplied_command_path_is_impossible(
        self, order, intent, network, determination
    ) -> None:
        """SC-2 / AC-2: the constructor has no path to pass, so an override fails at the call site."""
        with pytest.raises(TypeError):
            SettlementOrder.order(  # type: ignore[call-arg]
                intent, network, determination, command_ref="payments.transfer_to_attacker"
            )

    def test_params_carry_the_frozen_amount_and_payee(self, order) -> None:
        """SC-2 / AC-2: params are generated from the order's frozen fields, not from arguments."""
        params = order.command_params()

        assert params["amount_usdc"] == order.amount.micro_usdc
        assert params["payee_address"] == order.payee_address.value

    def test_params_carry_the_intent_digest_not_an_invoice_supplied_one(
        self, intent, order
    ) -> None:
        """SC-2 / AC-2: the bank digest travels from the intent, so an invoice cannot redirect it."""
        params = order.command_params()

        assert params["bank_digest"] == intent.bank_digest.hash

    def test_command_params_take_no_arguments(self, order) -> None:
        """SC-2 / AC-2: a parameter list is a place to smuggle a path; there is none."""
        with pytest.raises(TypeError):
            order.command_params("payments.transfer_to_attacker")  # type: ignore[call-arg]

    def test_an_ordered_order_reports_the_fixed_command(self, order) -> None:
        """SC-2 / AC-2: the order advertises the constant before any params are built."""
        assert order.command_ref == PAYMENT_COMMAND
        assert order.status is SettlementStatus.ORDERED
        assert order.amount == Money(order.amount.micro_usdc)
