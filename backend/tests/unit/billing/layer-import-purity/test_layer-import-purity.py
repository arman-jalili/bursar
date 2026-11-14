"""B-3 / AC #8 — the Billing domain is framework-free and points inward.

Canonical: docs/architecture/modules/billing.md#acceptance-criteria
Reference: docs/architecture/decisions/ADR-001-architecture-pattern.md

Asserts the dependency rule as a *rule*, not a style preference: no file under `src/billing/domain/`
may import FastAPI, SQLAlchemy, httpx (or any other web/ORM framework), and it may not import the
module's own outer layers. The domain must be testable without a server, a database or a socket — that
is what lets the aggregate rules be proven in milliseconds.

AST parsing rather than grep: a comment or docstring mentioning `sqlalchemy` is not an import, and a
grep-based check would both false-positive on documentation and miss `importlib` tricks.
"""

from __future__ import annotations

import ast
from pathlib import Path

DOMAIN = Path(__file__).resolve().parents[4] / "src" / "billing" / "domain"

#: Frameworks that must never reach the model.
FORBIDDEN_ROOTS = frozenset(
    {"fastapi", "sqlalchemy", "httpx", "flask", "django", "peewee", "tortoise"}
)

#: The module's own outer layers: the domain may not depend on them either.
FORBIDDEN_INNER_PREFIXES = (
    "src.billing.application",
    "src.billing.infrastructure",
    "src.billing.interfaces",
)


def _domain_files() -> list[Path]:
    files = sorted(DOMAIN.rglob("*.py"))
    assert files, f"no domain files found under {DOMAIN}"
    return files


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


class TestLayerImportPurity:
    def test_the_domain_imports_no_web_or_orm_framework(self) -> None:
        """AC #8: FastAPI, SQLAlchemy and httpx are outer-layer concerns."""
        violations: list[str] = []
        for path in _domain_files():
            for module in _imported_modules(path):
                root = module.split(".", 1)[0]
                if root in FORBIDDEN_ROOTS:
                    violations.append(
                        f"{path.relative_to(DOMAIN.parent.parent.parent)} -> {module}"
                    )
        assert not violations, f"domain imported a framework: {violations}"

    def test_the_domain_does_not_import_its_own_outer_layers(self) -> None:
        """ADR-001: the arrows point inward — domain never depends on application/infra/interfaces."""
        violations: list[str] = []
        for path in _domain_files():
            for module in _imported_modules(path):
                if module.startswith(FORBIDDEN_INNER_PREFIXES):
                    violations.append(f"{path.name} -> {module}")
        assert not violations, f"domain imported an outer layer: {violations}"

    def test_adapters_implement_domain_owned_ports(self) -> None:
        """ADR-008 interface-ownership: the ABC lives in domain/, the SQL adapter implements it."""
        from src.billing.domain.repositories import (
            InvoiceRepository,
            PaymentAttemptRepository,
        )
        from src.billing.infrastructure.repositories import (
            SqlInvoiceRepository,
            SqlPaymentAttemptRepository,
        )

        assert issubclass(SqlInvoiceRepository, InvoiceRepository)
        assert issubclass(SqlPaymentAttemptRepository, PaymentAttemptRepository)
