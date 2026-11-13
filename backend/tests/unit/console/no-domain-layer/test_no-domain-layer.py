"""CON-09 — the console has no domain layer, and its appearance must fail, not be reviewed.

Canonical: .pi/architecture/modules/console.md#architecture
Reference: docs/contracts/console-contract-freeze.md §1 (CON-09), §2.10

ADR-008: a generic subdomain is modelled at adapter depth. The danger is a "small" value object
appearing in `src/console/domain/` during Phase B and quietly moving a rule out of Authority. The
absence is checked mechanically, not remembered.
"""

from __future__ import annotations

from pathlib import Path

import src.console
from src.console.infrastructure.purity import FORBIDDEN_LAYERS, declared_layers

CONSOLE_PACKAGE = Path(src.console.__file__).resolve().parent


class TestNoDomainLayer:
    def test_the_declared_layers_contain_no_domain_layer(self) -> None:
        """CON-09: the declared set is what the gate reads; a domain entry fails the build."""
        layers = declared_layers()
        assert "domain" not in layers
        assert set(layers) == {"application", "infrastructure", "interfaces"}

    def test_the_console_package_has_no_domain_directory(self) -> None:
        """CON-09: the directory is the violation; a layer nothing imports is still a layer."""
        assert not (CONSOLE_PACKAGE / "domain").exists()

    def test_the_only_forbidden_layer_is_domain(self) -> None:
        """CON-09: infrastructure/application/interfaces are expected; "domain" is the one to refuse."""
        assert FORBIDDEN_LAYERS == ("domain",)
