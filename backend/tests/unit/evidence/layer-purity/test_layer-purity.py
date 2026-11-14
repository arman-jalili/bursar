"""E-11 — `src/evidence/domain/` imports no FastAPI, SQLAlchemy or web3.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: docs/architecture/decisions/ADR-001-architecture-pattern.md

The domain must be testable without a web framework, an ORM or a chain client. This is enforced by
scanning imports, not by convention. The second assertion keeps the test honest: canonical hashing is
domain computation, so the suite fails today from the `EnvelopeHash.compute` stub rather than passing
on an import scan alone.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.evidence.domain.values import EnvelopeHash

FORBIDDEN = ("fastapi", "sqlalchemy", "web3")


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


class TestLayerPurity:
    def test_domain_hashing_is_pure_and_has_no_web_or_orm_imports(self) -> None:
        """E-11: no forbidden import, and the hash is computed in the domain (not an adapter)."""
        domain = Path(__file__).parents[4] / "src" / "evidence" / "domain"
        forbidden: list[str] = []
        for path in sorted(domain.glob("*.py")):
            for module in _imported_modules(path):
                if any(module == name or module.startswith(f"{name}.") for name in FORBIDDEN):
                    forbidden.append(f"{path.name}: {module}")

        assert forbidden == []
        assert EnvelopeHash.compute(b"{}", "hmac").value
