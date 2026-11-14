"""A-9 / A-10 — the ports are domain-owned and express the ledger's atomicity.

Canonical: docs/contracts/authority-contract-freeze.md §2
Reference: docs/architecture/decisions/ADR-002-data-storage-strategy.md

`try_reserve_atomic` returning a bool is A-9 written as a signature: one conditional update, and False when
it matched no row. A port that returned the ledger instead would invite read-then-write, which is the exact
bug the invariant names. Asserted as rules: no transaction control, and appends have no update path.
"""

from __future__ import annotations

import inspect

import pytest
from src.authority.domain import repositories
from src.authority.domain.repositories import (
    ApprovalRepository,
    CapLedgerRepository,
    DeterminationRepository,
    PaymentIntentRepository,
)


class TestPortsExpressInvariants:
    def test_the_ledger_port_reports_atomic_success_as_a_bool(self) -> None:
        """A-9: `try_reserve_atomic` returns bool — the adapter says whether the UPDATE matched."""
        annotation = inspect.signature(CapLedgerRepository.try_reserve_atomic).return_annotation
        assert annotation in (bool, "bool")

    def test_the_ledger_port_takes_the_day_and_the_amount_together(self) -> None:
        """A-9/A-12: the conditional update needs both in one call, or it is two round trips."""
        parameters = inspect.signature(CapLedgerRepository.try_reserve_atomic).parameters
        assert {"day", "amount", "reservation"} <= set(parameters)

    def test_determinations_are_append_only(self) -> None:
        """A-7: no `save` on the determination port — a verdict cannot be revised after the fact."""
        assert hasattr(DeterminationRepository, "append")
        assert not hasattr(DeterminationRepository, "save")

    def test_no_port_exposes_transaction_control(self) -> None:
        """ADR-002: the unit of work lives in `application/`; a committing port would break A-9."""
        forbidden = {"commit", "flush", "begin", "rollback"}
        for port in (
            PaymentIntentRepository,
            DeterminationRepository,
            CapLedgerRepository,
            ApprovalRepository,
        ):
            names = set(dir(port))
            assert not (names & forbidden), f"{port.__name__} exposes {names & forbidden}"

    def test_the_ports_live_in_the_domain_layer(self) -> None:
        """ADR-008: the domain owns the abstraction the adapters implement."""
        assert repositories.__file__.split("/")[-2] == "domain"

    def test_the_atomic_port_exists_because_the_aggregate_refuses(self) -> None:
        """A-9 end to end: the conditional UPDATE mirrors a rule the ledger enforces in memory.

        Red now (Phase-B bodies). Asserted together because an atomic adapter over a permissive aggregate
        would still over-book: both halves must refuse.
        """
        from src.authority.domain.cap_ledger import CapLedger
        from src.authority.domain.errors import CapExceeded

        from tests.unit.authority._builders import NOW, an_intent_id, usdc

        ledger = CapLedger(
            day="2026-11-14", cap=usdc("150"), committed=usdc("150"), reserved=usdc("0")
        )

        with pytest.raises(CapExceeded):
            ledger.try_reserve(an_intent_id(), usdc("25"), NOW)

    def test_resolve_is_the_single_commit_or_release_entry_point(self) -> None:
        """A-10: one method with an outcome, so there is no second path that resolves a hold."""
        names = {name for name, _ in inspect.getmembers(CapLedgerRepository, inspect.isfunction)}
        assert "resolve" in names
        assert not {"commit", "release"} & names
