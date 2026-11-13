"""Layer purity seam — the console declares its layers so the gate can check them (CON-09).

Canonical: .pi/architecture/modules/console.md#architecture
Reference: docs/contracts/console-contract-freeze.md §2.10

`src/console/domain/` does not exist and must not be created (ADR-008). This module is the seam the
adapter-purity gate calls, so the gate and the implementation cannot disagree about which layers
exist. It is frozen here rather than written in a validator script because the guarantee is the
module's, not the tool's.
"""

from __future__ import annotations

from typing import Final

__all__ = ["FORBIDDEN_LAYERS", "declared_layers"]

#: ADR-008: a generic subdomain is modelled as an adapter, not as a tactical domain.
FORBIDDEN_LAYERS: Final[tuple[str, ...]] = ("domain",)


def declared_layers() -> tuple[str, ...]:
    """Return the console's real layer packages, refusing if a forbidden one appeared (CON-09).

    Raises:
        DomainLayerPresent: `domain` is among the declared layers or exists on disk.
    """
    raise NotImplementedError("CON-09 — see module doc")
