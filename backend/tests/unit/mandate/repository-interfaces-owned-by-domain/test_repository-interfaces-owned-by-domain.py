"""Contract tests — repository ports are owned by `domain/` (mandate v1, ADR-008).

Canonical: .pi/architecture/modules/mandate.md#components
Reference: .pi/architecture/decisions/ADR-002-data-storage-strategy.md

This is the file that keeps the dependency arrow pointing the right way. Three rules are asserted:

1. The **interface** lives in `src/mandate/domain/repositories.py` and is an ABC whose methods are
   all abstract — an adapter cannot be written against a concrete class.
2. **No commit / no flush** appears in any domain repository signature: transaction placement belongs
   to `application/` (`txn-placement` gate), and the cap invariant depends on it.
3. Every **read is read-through** — `find_in_force` is its own method so Authority's dispatch-time
   read has one cache-free call site (FR-012).

The issue boilerplate suggested `infrastructure/repository/`; that contradicts ADR-008's
`interface-ownership` gate and the module doc's own "Repository interfaces (owned by `domain/`)".
The gate wins: implementations go to `infrastructure/`, interfaces stay here.

Rewritten from the generated placeholder (hyphenated method names → `SyntaxError`).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from src.mandate.domain import repositories
from src.mandate.domain.repositories import (
    ConstitutionRepository,
    HouseholdRepository,
    PayeeRepository,
)

DOMAIN_DIR = Path(repositories.__file__).parent
REPOSITORIES = [HouseholdRepository, ConstitutionRepository, PayeeRepository]


@pytest.mark.parametrize("repo", REPOSITORIES)
class TestRepositoryContract:
    def test_is_an_abstract_base_class(self, repo: type) -> None:
        assert inspect.isabstract(repo), (
            f"{repo.__name__} must be abstract (a port, not an adapter)"
        )

    def test_has_no_concrete_public_method(self, repo: type) -> None:
        concrete = [
            name
            for name, member in inspect.getmembers(repo, predicate=inspect.isfunction)
            if not name.startswith("_") and not getattr(member, "__isabstractmethod__", False)
        ]
        assert concrete == [], f"{repo.__name__} has non-abstract methods: {concrete}"

    def test_methods_are_async(self, repo: type) -> None:
        """Persistence is I/O; a sync port would invite blocking calls inside a request."""
        methods = [
            member
            for name, member in inspect.getmembers(repo, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]
        assert methods
        for method in methods:
            assert inspect.iscoroutinefunction(method), (
                f"{repo.__name__}.{method.__name__} is not async"
            )

    def test_never_manages_transactions(self, repo: type) -> None:
        """ADR-002: the application service owns the unit of work, the repository participates."""
        forbidden = {"commit", "flush", "begin", "rollback", "transaction", "session"}
        names = {name for name, _ in inspect.getmembers(repo, predicate=inspect.isfunction)}
        assert not (names & forbidden), (
            f"{repo.__name__} exposes transaction control: {names & forbidden}"
        )

    def test_returns_domain_aggregates_not_rows(self, repo: type) -> None:
        """No ORM model, no dict: the database schema is explicitly outside the frozen contract."""
        source = inspect.getsource(repo)
        for banned in ("dict[", "Row", "Base", "Model", "Record"):
            assert banned not in source, f"{repo.__name__} leaks a persistence type ({banned})"


class TestReadThroughRequirement:
    def test_constitution_has_a_dedicated_in_force_read(self) -> None:
        """A single named call site is how "no cache at the moment of consequence" stays auditable."""
        assert hasattr(ConstitutionRepository, "find_in_force")
        signature = inspect.signature(ConstitutionRepository.find_in_force)
        assert list(signature.parameters) == ["self", "household_id"]

    def test_historical_versions_are_readable(self) -> None:
        """H-7: a refusal citing v2 must stay explainable after v4 exists."""
        assert hasattr(ConstitutionRepository, "find_version")
        assert list(inspect.signature(ConstitutionRepository.find_version).parameters) == [
            "self",
            "constitution_id",
            "number",
        ]

    def test_payees_are_listable_per_household(self) -> None:
        assert hasattr(PayeeRepository, "find_by_household")


class TestLayerPurity:
    """The dip-domain gate, asserted from inside the test suite so it fails locally, not in CI."""

    def test_domain_imports_no_framework(self) -> None:
        banned = ("fastapi", "sqlalchemy", "httpx", "starlette", "uvicorn", "pydantic")
        offenders: list[str] = []
        for path in DOMAIN_DIR.glob("*.py"):
            text = path.read_text()
            for line in text.splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                if any(
                    stripped.startswith(f"import {b}") or stripped.startswith(f"from {b}")
                    for b in banned
                ):
                    offenders.append(f"{path.name}: {stripped}")
        assert offenders == [], f"domain layer imports a framework: {offenders}"

    def test_repository_interfaces_live_in_domain(self) -> None:
        assert Path(repositories.__file__).parent.name == "domain"

    def test_no_transaction_control_anywhere_in_domain(self) -> None:
        for path in DOMAIN_DIR.glob("*.py"):
            text = path.read_text()
            assert ".commit()" not in text, f"{path.name} commits; only application/ may"
