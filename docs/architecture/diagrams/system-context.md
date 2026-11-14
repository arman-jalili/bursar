# System Context Diagram

**Session:** 432050ea-0419-44ba-8ac4-b239242634b4
**Status:** Accepted (see ADR-001)

## Context

Bursar is a delegated bill-paying agent for **one household**. An owner grants an AI agent a
signed, versioned mandate to pay a parent's recurring bills in USDC, while a machine-enforced
constitution and an on-chain second lock make it impossible for the agent — or a stolen
operator key — to pay the wrong payee, exceed the caps, or pay the same invoice twice.

## Actors

```mermaid
graph TB
    Owner["👤 Owner<br/>(adult child)<br/>rules + signatures"]
    Payer["👤 Payer<br/>(parent)<br/>read-only"]
    Agent["🤖 Agent<br/>(LLM)<br/>proposes only"]
    Adversary["🦹 Adversary<br/>scam invoice / injection"]

    Owner --> Console
    Payer --> Console
    Agent -->|"POST proposal"| Billing
    Adversary -.->|"poisoned invoice"| Billing

    subgraph Bursar["Bursar — modular monolith (Python)"]
        Console["Console<br/><i>generic — read models</i>"]
        Billing["Billing<br/><i>supporting</i>"]
        Authority["Authority<br/><i>core</i>"]
        Mandate["Mandate<br/><i>core</i>"]
        Settlement["Settlement<br/><i>core</i>"]
        Evidence["Evidence<br/><i>supporting</i>"]
    end

    Console --> Authority
    Console --> Evidence
    Console --> Mandate
    Billing --> Mandate
    Authority --> Mandate
    Authority --> Billing
    Settlement --> Authority
    Settlement --> Mandate
    Settlement --> Evidence
    Evidence --> Authority

    Authority -.->|"precondition call<br/>(Lock 2)"| Rigorix
    Settlement -->|"run_command<br/>(Lock 1)"| Rigorix
    Rigorix -->|"USDC transfer"| Router
    Router -->|"settles"| Chain[("Base Sepolia /<br/>Anvil")]
    Router -.->|"anchor hash"| Chain
```

## Trust boundaries

```mermaid
graph LR
    subgraph AgentZone["⚠️ Agent-writable zone"]
        Agent["Agent process"]
        Workspace["workspace files"]
    end
    subgraph OperatorZone["🔒 Operator zone (agent cannot write)"]
        RigorixCfg[".rigorix/*.toml"]
        AuthoritySvc["authority-service<br/>:8001 + SQLite"]
        PrecondClient["precondition client<br/>(thin HTTP)"]
        Keys["HMAC key · API keys<br/>settlement wallet key"]
    end
    subgraph ChainZone["⛓️ Commit point"]
        Router["PaymentRouter.sol"]
    end

    Agent -->|"proposals only"| AuthoritySvc
    RigorixCfg --> PrecondClient
    PrecondClient -->|"HTTP: may this move?"| AuthoritySvc
    Keys --> AuthoritySvc
    Keys --> Router
    AuthoritySvc -->|"allow → dispatch"| Router
    Router -->|"REVERT = terminal"| AuthoritySvc
```

**Reading this:** the agent can *ask* from the agent zone. It cannot write the config, cannot
reach the SQLite ledger, cannot hold the HMAC key, and cannot sign. The only path from a
proposal to money is `Authority allow → Rigorix dispatch → Router accept`.

## Deployment view

| Deployable | Port | Storage | CORS | Owns |
|---|---|---|---|---|
| `authority-service` | 8001 | `data/authority.db` | no | Authority |
| `console-api` | 8000 | `data/bursar.db` | yes (Vite origin) | Console, Mandate, Billing, Settlement, Evidence |
| `rigorix-server` | 8080 | its own | no | enforcement config + audit |
| React console | 5173 | — | — | UI |
| Anvil | 8545 | — | — | chain (demo) |

Rationale for the split: the agent's process must not be able to reach Authority's database or
its signing material (NFR-003). Everything else stays in one process to fit the timebox.

## Bounded Context Flow (summary)

```mermaid
graph LR
    A["Mandate<br/>core"]
    B["Billing<br/>supporting"]
    C["Authority<br/>core"]
    D["Settlement<br/>core"]
    E["Evidence<br/>supporting"]
    F["Console<br/>generic"]

    A -->|"constitution in force,<br/>payee eligibility"| C
    A -->|"verified digest"| B
    A -->|"payee address"| D
    B -->|"PaymentProposed"| C
    C -->|"PaymentAllowed"| D
    C -->|"determinations,<br/>refusals"| E
    D -->|"receipts, reverts"| E
    D -->|"outcome"| C
    E -->|"verification"| F
    C -->|"read models"| F
    A -->|"read models"| F

    style A fill:#1f6feb,color:#fff
    style C fill:#1f6feb,color:#fff
    style D fill:#1f6feb,color:#fff
    style B fill:#6e7681,color:#fff
    style E fill:#6e7681,color:#fff
    style F fill:#3d444d,color:#fff
```

Blue = core (full tactical DDD), grey = supporting (service depth), dark = generic (adapter).

## Core claim in one line

A payment can only exist if **Authority read the constitution at that instant**, **the owner
signed those exact bytes if required**, and **the chain had not seen that nullifier before**.
All three failures are refusals, and all three refusals are sealed as evidence.

---

*Generated from session: 432050ea-0419-44ba-8ac4-b239242634b4*
*Date: 2026-11-13*