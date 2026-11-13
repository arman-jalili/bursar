# Bursar — frozen build contract

**Status:** frozen 2026-11-13. This file is the seam between parallel workstreams. It is
deliberately **not** part of `.pi/context/prompt.md`; domain exploration reads the intent, not
this contract.

Hackathon: Proximata '26 — "Bringing Crypto to Everyday Life". Code freeze 14 Nov 15:00.

## Workstreams and ownership

| Track | Owns | Can start without |
|---|---|---|
| **A. Governance** | `backend/` console, `.rigorix/` policy, Rigorix integration, scenarios | frontend, chain |
| **B. Frontend** | `web/` React/TS/Vite, design system, 3 panes, approval sheet, verifier | backend (mocks) |
| **C. Chain** | `contracts/` Foundry, `PaymentRouter`, deploy scripts, Anvil | app (tests only) |
| **D. Authority** | `authority/` FastAPI + SQLite, determinations, reservations | UI (API contract) |
| **E. Integration** | `docker-compose.yml`, hosted deploy, demo script, video | A–D at the seams |

## Console API

```ts
type Mode = "base-sepolia" | "anvil";

type AttemptStatus =
  | "planned" | "pending_approval" | "allowed" | "refused"
  | "dispatched" | "settled" | "ambiguous" | "failed";

type Payee = {
  id: string;
  name: string;
  address: string;
  frozen: boolean;
  new: boolean;
};

type Attempt = {
  id: string;
  invoiceId: string;
  payee: Payee;
  amountUsdc: string;             // micro-units, string
  status: AttemptStatus;
  createdAt: string;
  decision?: {
    allow: boolean;
    source: "rigorix-plan" | "rigorix-dispatch" | "authority" | "contract";
    rule?: string;                // e.g. "no-bank-change-then-pay"
    reason?: string;
    decisionDigest?: string;
  };
  rigorix?: {
    executionId: string;
    envelopeHash?: string;
    envelopeUri?: string;         // /api/attempts/:id/envelope
    anchoredTx?: string;
  };
  settlement?: {
    txHash?: string;
    block?: number;
    receipt?: string;
  };
  narrative: string;              // agent's plain-language line, never enforcement
};

type Policy = {
  dailyCapUsdc: string;
  perPayeeCapUsdc: string;
  approvalThresholdUsdc: string;
  allowlist: Payee[];
  quarantineOnBankChange: boolean;
  frozenPayeeIds: string[];
};

type ApprovalRequest = {
  attemptId: string;
  intentDigest: string;
  invoiceId: string;
  payee: Payee;
  amountUsdc: string;
  nonce: string;
  deadline: string;
  eip712: {
    domain: Record<string, unknown>;
    types: Record<string, unknown>;
    message: Record<string, unknown>;
  };
};
```

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | `{ household, policy, mode, capacity, chain }` |
| GET | `/api/invoices` | Invoice list |
| GET | `/api/attempts` | Attempt list for the Agent and Receipts panes |
| GET | `/api/attempts/:id` | Attempt + envelope + events |
| GET | `/api/attempts/:id/envelope` | Raw signed envelope for browser verification |
| POST | `/api/attempts/:id/approve` | `{ signature, ownerAddress, nonce, deadline }` |
| POST | `/api/attempts/:id/deny` | Deny an approval request |
| POST | `/api/policy` | Owner-only rule changes |
| POST | `/api/payees/:id/freeze` | Freeze a payee |
| POST | `/api/payees/:id/reverify` | Clear a bank-change quarantine |
| POST | `/api/scenarios/:id` | Demo controls |
| GET | `/api/events` | SSE stream |

### SSE events

- `attempt.updated` — full `Attempt`
- `capacity.updated` — `{ committed, reserved, cap }`
- `approval.requested` — `ApprovalRequest`
- `chain.updated` — `{ txHash, block, status }`

The UI is event-driven; polling is only a reconnect fallback.

## Chain surface

```solidity
event PaymentSettled(
  bytes32 indexed invoiceId,
  address indexed payee,
  uint256 amount,
  bytes32 intentDigest,
  bytes32 decisionDigest
);

event EvidenceAnchored(bytes32 indexed envelopeHash, uint64 at);

function pay(
  bytes32 invoiceId,
  address payee,
  uint256 amount,
  bytes32 intentDigest,
  bytes32 decisionDigest,
  uint256 nonce,
  uint256 deadline,
  bytes calldata ownerSig
) external onlyOperator;

function anchor(bytes32 envelopeHash) external onlyOperator;
```

ABI and deployed addresses live in `config/chain.json` from day 0. The frontend renders links
without knowing the app.

## UI contract

- **Agent pane:** chronological attempt cards; status chip; the agent's line; a "why" link to
  the rule.
- **Constitution pane:** clauses with live values; the clause that refused gets a red margin
  note and stays highlighted until the next action.
- **Receipts pane:** attempt table; expanding a row shows the envelope JSON, Verify (browser),
  Flip one byte, anchor link, settle tx.
- **Approval sheet:** phone-sized paper slip; payee, amount, intent digest; Sign & approve; Deny.
- **Demo drawer:** scenario buttons, clearly labeled "Demo controls".

## Design tokens (frozen)

| Token | Value |
|---|---|
| Paper | `#F7F3EC` |
| Ink | `#1C1B19` |
| Oxblood | `#7A2E2E` |
| Muted gold | `#B08D57` |
| Rule line | `#D9D2C5` |
| Display | Fraunces or Newsreader |
| Body | Inter |
| Mono | JetBrains Mono |
| Spacing | 8 px scale |
| Radius | 2 px |
| Motion | subtle; no gradients, no glass |

## Frontend mocks

Five attempts: `settled`, `refused` (plan), `refused` (dispatch), `pending_approval`,
`ambiguous`. One approval request, one valid envelope, one flipped-byte envelope.

## Analyst gates (24-hour version)

| Gate | When | Pass condition |
|---|---|---|
| **G0** | H+1 | Intent + context map + API/ABI/tokens frozen; scenarios mapped to modules |
| **G1** | H+5 | UI shell runs on mocks; all five states designed; no backend calls |
| **G2** | H+12 | Normal pay + one refusal + browser evidence verification, end-to-end |
| **G3** | H+17 | Approval or freeze-at-dispatch works; wrong signature refused |
| **G4** | H+20 | Contract enforces allowlist/nullifier/owner signature; Base Sepolia or Anvil |
| **G5** | H+22 | Hosted URL + `docker compose up` + 3-minute script + README/.env.example/MIT |

## Non-goals for the 24-hour build

- Multi-household, auth, roles, Postgres.
- Capacity ledger and effect-commitment scenes (the authority service covers monetary caps).
- Passkey / smart account; EIP-712 wallet signature is the approval mechanism.
- LLM agent mode; the demo agent is deterministic with optional narration.
- Real bank payout; it is simulated and labeled.
