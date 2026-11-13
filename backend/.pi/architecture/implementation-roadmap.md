# Implementation Roadmap

<!--
@canonical .pi/architecture/implementation-roadmap.md
Status: Proposed
Date: [Date]
-->

## Overview

This roadmap defines the phased implementation of the project, organizing bounded
contexts into delivery phases with explicit dependencies, database migrations, and
acceptance criteria.

**Format conventions:**
- `## Phase 0: Project Bootstrap` is MINIMUM project setup (build/deps, shared kernel layout,
  config, error envelope, migration tooling, CI + validators, test harness, entrypoint). It is
  NOT a bounded context: no `### Modules` rows and no context folders (context folders are
  created in each context's own build phase)
- Each `## Phase N` (N≥1) section defines one delivery phase
- `### Modules` table lists ONLY the bounded contexts built in this phase (contexts start Phase 1)
- **Invariant:** each bounded context appears in exactly ONE phase's `### Modules` table
  (its build phase). Modules a phase merely uses are referenced under `### Dependencies`,
  never re-listed as Modules (no repeats, no "All")
- `### Dependencies` lists upstream phases AND the modules they provide (keep these
  references — implementation agents use them)
- `### Database Migrations` lists SQL migration files
- `### Acceptance Criteria` lists verifiable checkboxes

---

## Phase 0: [Phase Name] (Days [Start]–[End])

**Goal:** [One-sentence goal for this phase]

### Modules

| Module | Deliverables | Architecture Doc |
|--------|-------------|------------------|
| [Module Name] | [Key deliverables] | `.pi/architecture/modules/[module].md` |
| [Module Name] | [Key deliverables] | `.pi/architecture/modules/[module].md` |

### Dependencies

- [Phase name or "None"]

### Database Migrations

- `NNN_[migration_name]`: [Description of what it creates]

### Acceptance Criteria

- [ ] [Verifiable criterion]
- [ ] [Verifiable criterion]

---

## Phase 1: [Phase Name] (Days [Start]–[End])

**Goal:** [One-sentence goal for this phase]

### Modules

| Module | Deliverables | Architecture Doc |
|--------|-------------|------------------|
| [Module Name] | [Key deliverables] | `.pi/architecture/modules/[module].md` |

### Dependencies

- Phase 0

### Database Migrations

- `NNN_[migration_name]`: [Description]

### Acceptance Criteria

- [ ] [Verifiable criterion]

---

## Dependency Graph

```
Phase 0 ([Name])
    │
    ▼
Phase 1 ([Name])
    │
    ▼
Phase 2 ([Name])
```

## Effort Estimates

| Phase | Modules | Estimated Days | Risk | Dependencies |
|-------|---------|---------------|------|-------------|
| P0: [Name] | [N] | [N] | [Low/Medium/High] | None |
| P1: [Name] | [N] | [N] | [Low/Medium/High] | P0 |
| P2: [Name] | [N] | [N] | [Low/Medium/High] | P1 |

## Key Milestones

| Milestone | Target | What's True |
|-----------|--------|-------------|
| **M0: [Name]** | Day [N] | [What's working] |
| **M1: [Name]** | Day [N] | [What's working] |
