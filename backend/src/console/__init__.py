"""Console — the edge that projects other contexts' state onto two human surfaces.

Canonical: .pi/architecture/modules/console.md#architecture
Reference: docs/contracts/console-contract-freeze.md

The console has **no domain layer** (CON-09): it composes read models, translates copy, and forwards
one signature. Business rules live in Authority, Mandate, Billing, Settlement and Evidence.

Phase B: the three projections, the six ACL whitelists, the six registered upstream ports and the
eight routes are implemented. There is still no `domain/` package and there never will be (CON-09).
"""

from __future__ import annotations

__all__: list[str] = []
