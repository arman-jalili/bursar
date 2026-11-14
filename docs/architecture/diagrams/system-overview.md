# System Architecture Overview

<!--
Canonical Reference: docs/architecture/diagrams/system-overview.md
-->

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         External Clients                         │
│                    (Web, Mobile, API Consumers)                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway Layer                         │
│              docs/architecture/modules/api-gateway.md             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Business Logic Layer                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Auth       │  │   Core       │  │   Workflow   │          │
│  │   Module     │  │   Module     │  │   Module     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Data Layer                                │
│              docs/architecture/modules/data-layer.md              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Database   │  │   Cache      │  │   Storage    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Module Layers

| Layer | Modules | Purpose | Entry Point |
|-------|---------|---------|-------------|
| Presentation | api-gateway | Request handling, routing | src/api/ |
| Business | auth-system, core, workflow | Domain logic | src/modules/ |
| Data | data-layer, cache, storage | Persistence | src/data/ |
| Infrastructure | config, logging, monitoring | Cross-cutting | src/lib/ |

---

## Module Dependency Graph

```
api-gateway
    │
    ├──→ auth-system
    │        │
    │        └──→ data-layer
    │
    ├──→ core-module
    │        │
    │        ├──→ data-layer
    │        │
    │        └──→ cache-layer
    │
    └──→ workflow-module
             │
             └──→ core-module
```

---

## Data Flow Overview

### Request Flow

```
Request → API Gateway → Auth Validation → Business Logic → Data Layer → Response
                              │
                              ▼
                         Cache Check
                              │
                              ▼
                        (if needed)
```

### Event Flow

```
Business Logic → Event Bus → Event Handlers → Side Effects
      │
      └──→ Logging/Metrics
```

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Load Balancer                            │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────┐        ┌─────────────┐        ┌─────────────┐
│   App       │        │   App       │        │   App       │
│   Instance  │        │   Instance  │        │   Instance  │
│   #1        │        │   #2        │        │   #3        │
└─────────────┘        └─────────────┘        └─────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   Shared Data   │
                    │   Layer         │
                    └─────────────────┘
```

---

## Security Boundaries

| Boundary | Enforcement | Module |
|----------|-------------|--------|
| External → API Gateway | Rate limiting, CORS | api-gateway |
| API Gateway → Business | Auth validation | auth-system |
| Business → Data | Query auth, encryption | data-layer |

---

## Key Integration Points

| Integration | Protocol | Module | Documentation |
|-------------|----------|--------|---------------|
| [API Name] | REST/GraphQL | api-gateway | docs/architecture/modules/api-gateway.md#integrations |
| [Database] | SQL/NoSQL | data-layer | docs/architecture/modules/data-layer.md#connections |
| [Cache] | Redis/Memory | cache-layer | docs/architecture/modules/cache-layer.md |

---

## Canonical Reference Template

Implementation files should reference this overview when describing system-level behavior:

```python
"""Canonical Reference: docs/architecture/diagrams/system-overview.md#[section]
Implements: [component at layer X]
"""
```

---

*Last updated: 2026-11-13*
*Architecture version: 1.0 (superseded by system-context.md + event-flow.md)*