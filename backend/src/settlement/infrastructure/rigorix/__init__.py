"""Rigorix adapters — the governed-execution host as an infrastructure detail.

Canonical: docs/architecture/modules/settlement.md#ports-infrastructure-adapters
Reference: docs/contracts/settlement-contract-freeze.md §2.8 (SC-2)

`RigorixCommandAdapter` implements the frozen `PaymentExecutor` port. It is the only place in this
context that knows Rigorix exists: the domain sees `CommandAck`, the aggregate sees an order.
"""

from __future__ import annotations

from src.settlement.infrastructure.rigorix.command_adapter import (
    DISPATCH_COMMAND,
    RigorixCommandAdapter,
)

__all__ = ["DISPATCH_COMMAND", "RigorixCommandAdapter"]
