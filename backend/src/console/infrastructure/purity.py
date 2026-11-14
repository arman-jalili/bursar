"""Layer purity seam — the console declares its layers so the gate can check them (CON-09).

Canonical: .pi/architecture/modules/console.md#architecture
Reference: docs/contracts/console-contract-freeze.md §2.10

`src/console/domain/` does not exist and must not be created (ADR-008). This module is the seam the
adapter-purity gate calls, so the gate and the implementation cannot disagree about which layers
exist. It is frozen here rather than written in a validator script because the guarantee is the
module's, not the tool's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from src.console.application.errors import DomainLayerPresent

__all__ = ["DECLARED_LAYERS", "FORBIDDEN_LAYERS", "declared_layers"]

#: ADR-008: a generic subdomain is modelled as an adapter, not as a tactical domain.
FORBIDDEN_LAYERS: Final[tuple[str, ...]] = ("domain",)

#: The three layers the console actually has. `interfaces` is the edge; there is no `domain`.
DECLARED_LAYERS: Final[tuple[str, ...]] = ("application", "infrastructure", "interfaces")


def _package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def declared_layers() -> tuple[str, ...]:
    """Return the console's real layer packages, refusing if a forbidden one appeared (CON-09).

    Raises:
        DomainLayerPresent: `domain` is among the declared layers or exists on disk.
    """
    package = _package_root()

    # Check the disk, not only the tuple: a layer nothing imports is still a layer.
    on_disk = tuple(sorted(entry.name for entry in package.iterdir() if entry.is_dir()))
    forbidden = tuple(layer for layer in FORBIDDEN_LAYERS if layer in on_disk)
    if forbidden:
        raise DomainLayerPresent(
            "src/console/domain/ exists — the console is an adapter (ADR-008), not a domain model"
        )

    declared = tuple(layer for layer in DECLARED_LAYERS if (package / layer).is_dir())
    missing = tuple(layer for layer in DECLARED_LAYERS if layer not in declared)
    if missing:
        raise DomainLayerPresent(f"console is missing declared layer package(s) {missing}")

    if set(declared) & set(FORBIDDEN_LAYERS):  # pragma: no cover - defensive
        raise DomainLayerPresent(
            f"forbidden layer(s) declared: {set(declared) & set(FORBIDDEN_LAYERS)}"
        )

    return declared
