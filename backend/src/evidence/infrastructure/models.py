"""Evidence tables — SQLAlchemy 2.0 models. Never imported by `domain/` or `application/`.

Canonical: docs/architecture/modules/evidence.md#persistence-contract
Reference: docs/contracts/evidence-contract-freeze.md §2.5

The storage mirrors three frozen rules:

* `evidence_envelopes` has no update/delete path in the adapter, and migration `003_evidence`
  installs `BEFORE UPDATE`/`BEFORE DELETE` triggers so a hand-written statement cannot rewrite a
  sealed fact either (E-5).
* `uq_evidence_anchors_hash` is the storage half of `Anchor.matches` (E-8): one hash, one anchor.
* `evidence_processed_events` is keyed by `(event_id, handler)` — the idempotency key claimed before
  an append (E-4).

The operator HMAC key is deliberately absent from every column: it lives in the signer adapter only
(E-9).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = ["AnchorRow", "Base", "EnvelopeRow", "ProcessedEventRow"]

#: The closed anchoring-mode set (ADR-006). A typo cannot become a fourth mode.
_ANCHOR_MODES = ("per_envelope", "batched", "demo_only")


class Base(DeclarativeBase):
    """Declarative base for the Evidence schema (`evidence_*` tables)."""


class EnvelopeRow(Base):
    __tablename__ = "evidence_envelopes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_invoice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_payee_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    constitution_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actor: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hmac: Mapped[str] = mapped_column(Text, nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    anchor_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "anchor_mode IN ('" + "','".join(_ANCHOR_MODES) + "')",
            name="ck_evidence_envelopes_anchor_mode",
        ),
        Index("ix_evidence_envelopes_intent", "subject_intent_id"),
        Index("ix_evidence_envelopes_invoice", "subject_invoice_id"),
        Index("ix_evidence_envelopes_payee", "subject_payee_id"),
        Index("ix_evidence_envelopes_occurred", "occurred_at"),
        Index("ix_evidence_envelopes_event_type", "event_type"),
    )


class AnchorRow(Base):
    __tablename__ = "evidence_anchors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    envelope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    anchor_tx: Mapped[str] = mapped_column(Text, nullable=False)
    block_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    anchored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # E-8: the same hash cannot be anchored twice, and no second hash can borrow this proof.
        UniqueConstraint("envelope_hash", name="uq_evidence_anchors_hash"),
    )


class ProcessedEventRow(Base):
    """The idempotency ledger (E-4). A row is a claim; it is never updated or deleted."""

    __tablename__ = "evidence_processed_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    handler: Mapped[str] = mapped_column(String(40), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
