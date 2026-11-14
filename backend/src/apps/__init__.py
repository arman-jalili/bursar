"""Deployable composition roots.

Canonical: docs/architecture/decisions/ADR-001-architecture-pattern.md
Reference: docs/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

Two deployables by design (ADR-001), because the split is the security claim:

    authority_service/  :8001  Authority context — enforcement-critical, no CORS, its own DB file
    console_api/        :8000  everything else — browser-facing read models

The agent process must not be able to reach the authority database or its signing material
(NFR-003). That is why these are two processes and not one.
"""
