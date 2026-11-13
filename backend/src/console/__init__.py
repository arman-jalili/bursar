"""Console — the edge that projects other contexts' state onto two human surfaces.

Canonical: .pi/architecture/modules/console.md#architecture
Reference: docs/contracts/console-contract-freeze.md

The console has **no domain layer** (CON-09): it composes read models, translates copy, and forwards
one signature. Business rules live in Authority, Mandate, Billing, Settlement and Evidence.

Phase A: signatures only. Every behaviour body raises `NotImplementedError("CON-n — see module doc")`.
"""

from __future__ import annotations

__all__: list[str] = []
