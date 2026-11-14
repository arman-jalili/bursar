"""Mandate tables — SQLAlchemy 2.0 models. Never imported by `domain/` or `application/`.

Canonical: docs/architecture/modules/mandate.md#components
Reference: docs/architecture/decisions/ADR-002-data-storage-strategy.md

Design notes:

* **`version` is the optimistic-concurrency counter** (ADR-002): a save that carries a stale version
  is rejected, so two concurrent requests cannot each "win" on the same payee.
* **Digests are stored, routing details are not.** The raw account number exists only inside
  `BankDigest.from_routing_details`; the database never holds it, so a database leak cannot redirect
  a payment.
* **Constitution versions are rows, not JSON.** `find_version` (H-7) needs addressable history, and
  an audit wants to read one version without parsing a blob.
* **A partial unique index enforces one in-force version per household** (H-4) at the storage layer,
  where it cannot be forgotten.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

__all__ = ["Base", "ConstitutionRow", "ConstitutionVersionRow", "HouseholdRow", "PayeeRow"]


class Base(DeclarativeBase):
    """Declarative base for the Mandate schema (`mandate_*` tables)."""


class HouseholdRow(Base):
    __tablename__ = "mandate_households"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_address: Mapped[str] = mapped_column(String(42), nullable=False)
    owner_name: Mapped[str] = mapped_column(String(120), nullable=False)
    payer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    payer_contact: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_key_id: Mapped[str] = mapped_column(String(200), nullable=False)
    agent_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    constitution_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_mandate_households_owner", "owner_address"),)


class ConstitutionRow(Base):
    __tablename__ = "mandate_constitutions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    household_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    versions: Mapped[list[ConstitutionVersionRow]] = relationship(
        back_populates="constitution", order_by="ConstitutionVersionRow.number", lazy="selectin"
    )

    __table_args__ = (Index("ix_mandate_constitutions_household", "household_id"),)


class ConstitutionVersionRow(Base):
    __tablename__ = "mandate_constitution_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    constitution_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("mandate_constitutions.id"), nullable=False
    )
    household_id: Mapped[str] = mapped_column(String(64), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    cap_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False)
    require_signature_for_new_payee: Mapped[bool] = mapped_column(nullable=False, default=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_force")

    constitution: Mapped[ConstitutionRow] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("constitution_id", "number", name="uq_mandate_constitution_version"),
        # H-4 at the storage layer: at most one in-force version per household.
        Index(
            "uq_mandate_constitution_one_in_force",
            "household_id",
            unique=True,
            sqlite_where=text("status = 'in_force'"),
        ),
    )


class PayeeRow(Base):
    __tablename__ = "mandate_payees"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    household_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str] = mapped_column(String(42), nullable=False)
    verified_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # P-1: a payee name is unique inside a household (so the console list is unambiguous).
        UniqueConstraint("household_id", "name", name="uq_mandate_payee_name"),
        Index("ix_mandate_payees_status", "status"),
    )


class OutboxRow(Base):
    """Transactional outbox (ADR-003): events are written in the same transaction as the state."""

    __tablename__ = "mandate_outbox"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_name: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_mandate_outbox_unpublished", "published_at"),)
