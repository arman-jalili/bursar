"""AggregateRoot — the consistency boundary and the event recorder.

Canonical: docs/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: docs/architecture/modules/mandate.md#components

Two responsibilities, both structural:

1. **Consistency boundary.** One aggregate = one transactional boundary (ADR-002). Invariants
   that must hold "always" live inside a single aggregate; anything spanning aggregates is
   eventually consistent via events and must be stated as such.
2. **Event recorder.** A command method records facts; the application service, inside its unit
   of work, writes them to the outbox. Nothing publishes from inside the aggregate — an aggregate
   that talks to a bus is not testable and cannot be replayed.

Deliberate omissions, so they do not get added "for symmetry":

* No setters, no `update(**fields)`. State changes go through intention methods
  (`payee.freeze(actor)`), which is what keeps the invariants enforceable.
* No identity generation policy — ids come from the factory method so a rehydration from the
  database keeps the original id.
* No event dispatch. `pull_events()` drains; the caller decides what to do with them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from src.shared.domain.event import DomainEvent

__all__ = ["AggregateRoot"]


@dataclass(eq=False, kw_only=True)
class AggregateRoot:
    """Base for aggregate roots. Identity-based equality, never state-based.

    `eq=False` matters: two `Payee` instances with identical fields but different ids are
    different payees. State equality on an entity is how identity bugs get introduced.

    `kw_only=True` matters for ergonomics: it keeps the inherited bookkeeping fields (`version`)
    out of the positional argument list, so a subclass can declare `id` or `name` without a
    default — which is the shape every module doc stub uses.
    """

    #: Set to `entity`/`aggregate-root` in the module docs; asserted by architecture tests.
    _model_kind: ClassVar[str] = "aggregate-root"

    #: Optimistic-concurrency version. Starts at 0 for a new aggregate; the repository
    #: increments on save and rejects a stale write (ADR-002).
    version: int = field(default=0, compare=False, repr=False)

    _events: list[DomainEvent] = field(default_factory=list, init=False, repr=False, compare=False)

    # ── event recording ─────────────────────────────────────────────────────
    def record(self, event: DomainEvent) -> None:
        """Record a fact that already happened. Never validates, never fails."""
        self._events.append(event)

    def pull_events(self) -> tuple[DomainEvent, ...]:
        """Drain recorded events. Called once by the application service, inside its transaction.

        Returns a tuple so a caller cannot mutate the drained batch in place.
        """
        drained = tuple(self._events)
        self._events.clear()
        return drained

    @property
    def pending_events(self) -> tuple[DomainEvent, ...]:
        """Inspect without draining — for assertions in unit tests."""
        return tuple(self._events)

    def __repr__(self) -> str:
        ident = getattr(self, "id", "?")
        return f"<{type(self).__name__} id={ident!r} v{self.version}>"
