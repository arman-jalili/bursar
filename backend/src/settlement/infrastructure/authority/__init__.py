"""Authority adapters — the dispatch gate reads Authority live, and never invents a verdict (SC-1).

Canonical: docs/architecture/modules/settlement.md#dependencies
Reference: docs/contracts/settlement-contract-freeze.md §2.8 (SC-1)
"""

from __future__ import annotations

from src.settlement.infrastructure.authority.determination_gate import (
    DEMO_AUTHORITY_READ_TOKEN,
    AuthorityHttpAdapter,
)

__all__ = ["DEMO_AUTHORITY_READ_TOKEN", "AuthorityHttpAdapter"]
