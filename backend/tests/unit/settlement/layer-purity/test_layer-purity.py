"""SC-12 — `src/settlement/domain/` imports no web3, httpx or fastapi, and refuses through the shared vocabulary.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-12)
Reference: .pi/architecture/decisions/ADR-001-architecture-pattern.md

Defends module AC #12. Two independent claims, both rules:

1. **Dependency purity.** The domain is the layer that must be testable without a chain or an HTTP client.
   An import of `web3`, `httpx` or `fastapi` anywhere under `domain/` means a unit test of SC-1 would need
   the infrastructure it is supposed to be independent of. The scan is over the real files, so it keeps
   holding as Phase B lands.
2. **Refusal purity.** Every refusal the domain raises is a `SettlementRefusal` (itself a shared
   `RefusalError`), so the envelope handler needs no Settlement-specific branch and a refusal can never
   surface as a 500. A `ValueError` escaping the domain would be reported as a server fault — the exact
   misreport ADR-004 exists to prevent.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from src.authority.domain.values import DeterminationVerdict
from src.settlement.domain.errors import DispatchWithoutAuthority, SettlementRefusal
from src.settlement.domain.settlement_order import SettlementOrder

from tests.unit.settlement._fixtures import a_determination

DOMAIN = Path(__file__).resolve().parents[4] / "src" / "settlement" / "domain"
FORBIDDEN = frozenset({"web3", "eth_account", "httpx", "fastapi", "requests", "starlette"})
OUTER = frozenset({"application", "infrastructure", "interfaces"})


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _leaks(allowed: frozenset[str]) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {}
    for path in sorted(DOMAIN.glob("*.py")):
        hits = sorted(
            imported
            for imported in _imports(path)
            if imported.split(".")[0] in allowed
            or any(part in allowed for part in imported.split("."))
        )
        if hits:
            offenders[path.name] = hits
    return offenders


class TestDomainPurity:
    def test_the_domain_imports_no_chain_or_web_frameworks(self) -> None:
        """SC-12 / AC-12: no web3/httpx/fastapi anywhere under `src/settlement/domain/`."""
        assert _leaks(FORBIDDEN) == {}

    def test_the_domain_does_not_import_outward_layers(self) -> None:
        """SC-12 / AC-12: the dependency direction is inward only — domain knows nothing outward."""
        assert _leaks(OUTER) == {}

    def test_the_domain_refuses_through_the_shared_vocabulary(self, intent, network) -> None:
        """SC-12 / AC-12: a refusal is a `SettlementRefusal`, so it reaches the client as a documented 409."""
        denial = a_determination(DeterminationVerdict.DENY, intent_id=intent.intent_id)

        with pytest.raises(SettlementRefusal):
            SettlementOrder.order(intent, network, denial)

    def test_dispatch_without_authority_is_a_refusal_not_a_value_error(
        self, intent, network
    ) -> None:
        """SC-12 / AC-12: the specific class and the base class agree — one vocabulary, no outliers."""
        denial = a_determination(DeterminationVerdict.DENY, intent_id=intent.intent_id)

        with pytest.raises(DispatchWithoutAuthority):
            SettlementOrder.order(intent, network, denial)
