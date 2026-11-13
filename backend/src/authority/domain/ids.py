"""Authority identifiers — one NewType per aggregate/entity.

Canonical: .pi/architecture/modules/authority.md#components
Reference: docs/contracts/authority-contract-freeze.md

Four id types because four different things are addressed: an intent (the unit of authority), a
determination (the verdict), a reservation (the hold) and an approval (the signature request). Passing
one where another is expected is a realistic bug in a context this dense, and the checker catches it.
"""

from __future__ import annotations

import uuid
from typing import NewType

__all__ = ["ApprovalId", "DeterminationId", "IntentId", "ReservationId", "new_id"]

IntentId = NewType("IntentId", str)
DeterminationId = NewType("DeterminationId", str)
ReservationId = NewType("ReservationId", str)
ApprovalId = NewType("ApprovalId", str)


def new_id() -> str:
    """Fresh opaque identifier (uuid4 hex).

    The only body in this package that is allowed to do something: identifier generation is not
    behaviour, and stubbing it would force every test to invent ids.
    """
    return uuid.uuid4().hex
