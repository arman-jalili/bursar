// Console API client. Talks to the live console (default :8000) and maps its read
// models onto the console's view types. When the console is not up, the demo
// fixtures keep the whole product explorable offline.

import {
  CHAIN,
  INITIAL_APPROVAL,
  INITIAL_ATTEMPTS,
  INITIAL_POLICY,
  formatAmount,
  sumSettled,
} from "./data";
import type {
  ApprovalRequest,
  Attempt,
  AttemptStatus,
  ChainState,
  Mode,
  Payee,
  Policy,
} from "./data";

const CONSOLE_BASE =
  (import.meta.env.VITE_CONSOLE_API_URL as string | undefined) ?? "http://127.0.0.1:8000";
const OWNER_TOKEN =
  (import.meta.env.VITE_OWNER_TOKEN as string | undefined) ?? "demo-owner-token";
// Anvil account 0 — the household owner in the demo. It signs the intent digest and the router
// Payment digest. Public test key; never a real key.
export const DEMO_OWNER_KEY =
  (import.meta.env.VITE_DEMO_OWNER_KEY as string | undefined) ??
  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80";
const FORCE_MOCK = (import.meta.env.VITE_FORCE_MOCK as string | undefined) === "1";

export type Source = "api" | "mock";

export interface BursarState {
  household: { name: string; city: string };
  mode: Mode;
  policy: Policy;
  chain: ChainState;
  attempts: Attempt[];
  approval?: ApprovalRequest | null;
  source: Source;
}

// ── console wire shapes (freeze: backend/src/console/interfaces/schemas.py) ──

interface ConsoleApproval {
  approval_id: string;
  intent_id: string;
  invoice_id: string;
  payee_name: string;
  payee_address: string;
  amount_usdc: string;
  bank_digest: string;
  is_new_payee: boolean;
  requires_owner_signature: boolean;
  reason_codes: string[];
  expires_at: string;
  typed_data_hash: string;
}

interface ConsoleBill {
  invoice_id: string;
  payee_name: string;
  amount_usdc: string;
  status: string;
  status_plain: string;
  settled_at: string | null;
  tx_hash: string | null;
  payout_simulated: boolean;
  payout_label: string | null;
  refusal_reason: string | null;
}

interface ConsoleConstitution {
  version: string;
  cap_usdc: string;
  threshold_usdc: string;
  published_at: string;
}

interface ConsoleEvidence {
  envelope_id: string;
  event_type: string;
  occurred_at: string;
  result: string;
  anchor_tx: string | null;
}

interface ConsoleReadyz {
  status: string;
  service: string;
  config?: { chain?: string; chain_id?: number };
}

export interface ConsoleSignatureOutcome {
  granted: boolean;
  reason_plain?: string | null;
  reason_codes: string[];
}

export interface ConsoleVerification {
  envelope_id: string;
  outcome: string;
  checked_at: string;
  detail?: string;
}

// ── transport ─────────────────────────────────────────────────────────────

async function consoleGet<T>(path: string, timeoutMs = 3000): Promise<T> {
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${CONSOLE_BASE}${path}`, {
      headers: {
        accept: "application/json",
        authorization: `Bearer ${OWNER_TOKEN}`,
      },
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(id);
  }
}

async function consolePost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${CONSOLE_BASE}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
      authorization: `Bearer ${OWNER_TOKEN}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${path}: HTTP ${res.status}${text ? ` — ${text.slice(0, 200)}` : ""}`);
  }
  return (await res.json().catch(() => ({}))) as T;
}

// ── mapping ───────────────────────────────────────────────────────────────

const USDC_DP = 6;

// The console's demo rows are recorded on 2026-11-13; the product narrative is
// "Saturday, 14 November". Pin live rows to today's clock so the feed reads in order.
const DEMO_CLOCK = "2026-11-14T14:11:00+01:00";
const DEMO_DEADLINE = "2026-11-14T16:00:00+01:00";

/** Console amounts are exact decimal strings ("320.00"); the console view uses micro-units. */
export function decimalToUnits(value: string): string {
  const n = Number(value);
  return Number.isFinite(n) ? String(Math.round(n * 10 ** USDC_DP)) : "0";
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function mapBillStatus(status: string): AttemptStatus {
  switch (status.toUpperCase()) {
    case "SETTLED":
      return "settled";
    case "RECEIVED":
      return "planned";
    case "PENDING":
    case "PENDING_APPROVAL":
    case "AWAITING_APPROVAL":
      return "pending_approval";
    case "REFUSED":
    case "DENIED":
      return "refused";
    case "DISPATCHED":
    case "IN_FLIGHT":
      return "dispatched";
    case "FAILED":
      return "failed";
    default:
      return "planned";
  }
}

function approvalAttempt(item: ConsoleApproval, thresholdUsdc: string): Attempt {
  const payee: Payee = {
    id: slugify(item.payee_name),
    name: item.payee_name,
    address: item.payee_address,
    frozen: false,
    new: item.is_new_payee,
  };
  const rule = item.is_new_payee ? "new_payee" : "owner_signature";
  const line = formatAmount(thresholdUsdc);
  return {
    id: item.invoice_id,
    invoiceId: item.invoice_id,
    payee,
    amountUsdc: decimalToUnits(item.amount_usdc),
    status: "pending_approval",
    createdAt: DEMO_CLOCK,
    decision: {
      allow: false,
      source: "authority",
      rule,
      reason: item.is_new_payee
        ? `The payee is new and the amount is above the ${line} approval line.`
        : `The amount is above the ${line} approval line.`,
    },
    narrative: item.is_new_payee
      ? `A new payee, above your ${line} line. I have not paid it.`
      : `Above your ${line} line. I have not paid it.`,
    approvalId: item.approval_id,
  };
}

function approvalRequest(item: ConsoleApproval, attempt: Attempt): ApprovalRequest {
  return {
    approvalId: item.approval_id,
    intentId: item.intent_id,
    attemptId: attempt.id,
    intentDigest: item.typed_data_hash,
    invoiceId: item.invoice_id,
    payee: attempt.payee,
    amountUsdc: attempt.amountUsdc,
    nonce: item.intent_id,
    deadline:
      new Date(item.expires_at).getTime() > Date.now() ? item.expires_at : DEMO_DEADLINE,
    // The console does not expose Authority's typed-data document; the demo signer
    // posts through the passthrough and the console forwards the bytes unmodified.
    eip712: INITIAL_APPROVAL.eip712,
  };
}

function billAttempt(bill: ConsoleBill): Attempt {
  const status = mapBillStatus(bill.status);
  const payee: Payee = {
    id: slugify(bill.payee_name),
    name: bill.payee_name,
    address: "",
    frozen: false,
    new: false,
  };
  const base: Attempt = {
    id: bill.invoice_id,
    invoiceId: bill.invoice_id,
    payee,
    amountUsdc: decimalToUnits(bill.amount_usdc),
    status,
    createdAt: bill.settled_at ?? DEMO_CLOCK,
    narrative: bill.status_plain,
  };

  if (status === "settled") {
    return {
      ...base,
      decision: {
        allow: true,
        source: "rigorix-dispatch",
        rule: "standing-record",
        reason: bill.status_plain,
      },
      settlement: bill.tx_hash
        ? { txHash: bill.tx_hash, block: CHAIN.block, receipt: bill.tx_hash }
        : undefined,
      narrative: `${bill.payee_name} was paid. ${bill.payout_label ?? "USDC settled."}`,
    };
  }

  if (status === "refused") {
    return {
      ...base,
      decision: {
        allow: false,
        source: "authority",
        rule: "refused",
        reason: bill.refusal_reason ?? bill.status_plain,
      },
      narrative: bill.refusal_reason ?? `The payment to ${bill.payee_name} was refused.`,
    };
  }

  return {
    ...base,
    narrative:
      bill.status.toUpperCase() === "RECEIVED"
        ? "The bill has arrived. The agent has not paid it."
        : bill.status_plain,
  };
}

function attachEvidence(attempts: Attempt[], evidence: ConsoleEvidence[]): Attempt[] {
  const first = evidence[0];
  if (!first || attempts.length === 0) return attempts;
  return attempts.map((attempt, index) =>
    index === 0
      ? {
          ...attempt,
          evidenceId: first.envelope_id,
          evidenceEvent: first.event_type,
          evidenceResult: first.result,
          evidenceAt: first.occurred_at,
          anchorTx: first.anchor_tx ?? undefined,
        }
      : attempt,
  );
}

function mapConsole(
  constitution: ConsoleConstitution,
  approvals: ConsoleApproval[],
  bills: ConsoleBill[],
  evidence: ConsoleEvidence[],
  readyz: ConsoleReadyz | null,
): BursarState {
  const base = demoState();
  const policy: Policy = {
    ...base.policy,
    dailyCapUsdc: decimalToUnits(constitution.cap_usdc),
    approvalThresholdUsdc: decimalToUnits(constitution.threshold_usdc),
  };

  const approvalAttempts = approvals.map((item) =>
    approvalAttempt(item, policy.approvalThresholdUsdc),
  );
  const covered = new Set(approvals.map((item) => item.invoice_id));
  const billAttempts = bills.filter((bill) => !covered.has(bill.invoice_id)).map(billAttempt);
  const liveAttempts = attachEvidence([...approvalAttempts, ...billAttempts], evidence);

  const mode: Mode = readyz?.config?.chain === "anvil" ? "anvil" : CHAIN.mode;
  const chain: ChainState = { ...CHAIN, mode, sealed: evidence.length };

  const primary =
    approvals[0] && approvalAttempts[0]
      ? approvalRequest(approvals[0], approvalAttempts[0])
      : null;

  return {
    ...base,
    mode,
    policy,
    chain,
    // Live mode shows only what the backend actually holds: a fixture row beside a real
    // determination is how a demo starts lying. The story/lab remain a local overlay.
    attempts: liveAttempts.map((a) => ({ ...a, live: true })),
    approval: primary,
    source: "api",
  };
}

// ── public client ─────────────────────────────────────────────────────────

export const demoState = (): BursarState => ({
  household: { name: "The Weiss household", city: "Vienna" },
  mode: CHAIN.mode,
  policy: INITIAL_POLICY,
  chain: CHAIN,
  attempts: INITIAL_ATTEMPTS,
  approval: INITIAL_APPROVAL,
  source: "mock",
});

export async function loadState(): Promise<BursarState> {
  if (FORCE_MOCK) return demoState();
  try {
    const [constitution, approvals, bills, evidence, readyz] = await Promise.all([
      consoleGet<ConsoleConstitution>("/v1/console/constitution"),
      consoleGet<ConsoleApproval[]>("/v1/console/approvals"),
      consoleGet<ConsoleBill[]>("/v1/console/bills"),
      consoleGet<ConsoleEvidence[]>("/v1/console/evidence"),
      consoleGet<ConsoleReadyz>("/readyz", 2000).catch(() => null),
    ]);
    return mapConsole(constitution, approvals, bills, evidence, readyz);
  } catch {
    return demoState();
  }
}

export async function approveConsole(
  approvalId: string,
  signature: string,
): Promise<ConsoleSignatureOutcome> {
  return consolePost<ConsoleSignatureOutcome>(
    `/v1/console/approvals/${encodeURIComponent(approvalId)}/signature`,
    { signature_hex: signature },
  );
}

export async function verifyEvidence(envelopeId: string): Promise<ConsoleVerification> {
  return consoleGet<ConsoleVerification>(
    `/v1/console/evidence/${encodeURIComponent(envelopeId)}/verify`,
  );
}

function demoSignature(): { signature: string; ownerAddress: string } {
  return {
    signature: `0xdemo${Date.now().toString(16)}${"0".repeat(110)}`.slice(0, 132),
    ownerAddress: "0x5F2a9c1e0b4d7a6f3e2c1b0a9d8e7f6a5c4b3d21",
  };
}

export async function signApproval(request: ApprovalRequest): Promise<{
  signature: string;
  ownerAddress: string;
}> {
  // Console approvals: Authority verifies a secp256k1 signature over the intent's 32-byte digest.
  // The demo owner key is the Anvil account 0 key, so the signature is real and recoverable.
  if (request.approvalId) {
    const { Wallet } = await import("ethers");
    const wallet = new Wallet(DEMO_OWNER_KEY);
    return {
      signature: wallet.signingKey.sign(request.intentDigest).serialized,
      ownerAddress: wallet.address,
    };
  }

  const eth = (window as unknown as { ethereum?: unknown }).ethereum as
    | { request: (args: { method: string; params?: unknown[] }) => Promise<unknown> }
    | undefined;
  if (!eth) return demoSignature();

  const { BrowserProvider } = await import("ethers");
  const provider = new BrowserProvider(eth as never);
  const signer = await provider.getSigner();
  const signature = await signer.signTypedData(
    request.eip712.domain,
    request.eip712.types as never,
    request.eip712.message,
  );
  return { signature, ownerAddress: await signer.getAddress() };
}

export interface DispatchResult {
  order_id: string;
  intent_id: string;
  status: string;
  nullifier: string;
  tx_hash?: string | null;
}

/** Dispatch an authorised intent: authority gate -> local signing -> Rigorix broadcast. */
export async function dispatchIntent(intentId: string): Promise<DispatchResult> {
  const res = await fetch(`${CONSOLE_BASE}/v1/intents/${encodeURIComponent(intentId)}/dispatch`, {
    method: "POST",
    headers: { accept: "application/json", authorization: `Bearer ${OWNER_TOKEN}` },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `dispatch: HTTP ${res.status}`);
  }
  return (await res.json()) as DispatchResult;
}

export function settledToday(attempts: Attempt[]): number {
  return sumSettled(attempts);
}
