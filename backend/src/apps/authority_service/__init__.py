"""`authority-service` — enforcement-critical deployable (port 8001).

Canonical: docs/architecture/modules/authority.md#architecture
Reference: docs/architecture/decisions/ADR-007-compliance-engine-architecture.md

Hosts the Authority bounded context (Phase 3). No CORS, no agent-writable volume, its own SQLite
file (`data/authority.db`). Rigorix calls `POST /v1/precondition/check` here at the moment of
consequence (Lock 2 of three).
"""
