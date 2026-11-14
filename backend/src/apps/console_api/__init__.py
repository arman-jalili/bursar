"""`console-api` — browser-facing deployable (port 8000).

Canonical: docs/architecture/modules/console.md#architecture
Reference: docs/architecture/decisions/ADR-001-architecture-pattern.md

Hosts Console (Phase 6) plus the contexts that do not need process isolation: Mandate (1),
Billing (2), Settlement (4), Evidence (5). One database file (`data/bursar.db`), one process,
which is the honest engineering trade for a 24-hour build.
"""
