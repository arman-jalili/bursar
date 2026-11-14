"""Read models the browser-facing console needs from Mandate (display only).

The console's upstream contract asks for a current constitution and a payee list. Those are reads,
not use cases: nothing here changes state or emits an event.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.mandate.infrastructure.models import (
    ConstitutionVersionRow,
    HouseholdRow,
    PayeeRow,
)
from src.shared.application.unit_of_work import session_scope

__all__ = ["MandateQueries"]


def _usdc(micro: int) -> str:
    """Micro-USDC → the exact two-decimal string the console renders (never re-rendered later)."""
    return f"{micro / 1_000_000:.2f}"


class MandateQueries:
    """One household in the demo; the queries still read the rows rather than assume it."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def payees(self) -> list[dict[str, str]]:
        async with session_scope(self._factory) as session:
            result = await session.execute(select(PayeeRow).order_by(PayeeRow.name))
            return [
                {
                    "payee_id": row.id,
                    "display_name": row.name,
                    "status": row.status,
                }
                for row in result.scalars()
            ]

    async def constitution(self) -> dict[str, object]:
        """The in-force version, with the household's creation time as its published timestamp."""
        async with session_scope(self._factory) as session:
            result = await session.execute(
                select(ConstitutionVersionRow, HouseholdRow)
                .join(HouseholdRow, HouseholdRow.id == ConstitutionVersionRow.household_id)
                .where(ConstitutionVersionRow.status == "in_force")
                .order_by(ConstitutionVersionRow.number.desc())
                .limit(1)
            )
            row = result.first()
            if row is None:
                return {
                    "version": "0",
                    "cap_usdc": "0.00",
                    "threshold_usdc": "0.00",
                    "published_at": datetime.now(UTC).isoformat(),
                }
            version, household = row
            published = household.created_at
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            return {
                "version": f"c-{version.number}",
                "cap_usdc": _usdc(version.cap_micro_usdc),
                "threshold_usdc": _usdc(version.threshold_micro_usdc),
                "published_at": published.isoformat(),
            }
