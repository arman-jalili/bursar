// The chat agent + capacity gate. Every call hits the live console; nothing here is a fixture.

const BASE =
  (import.meta.env.VITE_CONSOLE_API_URL as string | undefined) ?? "http://127.0.0.1:8000";
const TOKEN = (import.meta.env.VITE_OWNER_TOKEN as string | undefined) ?? "demo-owner-token";

export interface Capacity {
  cap: string;
  committed: string;
  reserved: string;
  headroom: string;
}

export interface AgentPayee {
  id: string;
  name: string;
  status: string;
}

export interface ChainInfo {
  chain_id: number;
  usdc: string;
  router: string;
  treasury: string;
}

export interface AgentState {
  household: string;
  capacity: Capacity;
  threshold: string;
  payees: AgentPayee[];
  chain: ChainInfo;
  llm: { ready: boolean; model: string };
}

export interface GateStep {
  name: string;
  ok: boolean;
  detail: string;
}

/** One dispatch-time check Rigorix ran, as it recorded it on the signed envelope. */
export interface PreconditionFinding {
  precondition_id: string;
  step: string;
  outcome: "passed" | "failed" | "error" | string;
  exit_code?: number | null;
  inputs_hash: string;
  checked_at: string;
  summary: string;
  check_digest?: string | null;
  authority_digest?: string | null;
  check_writable?: boolean | null;
  attribution?: string | null;
}

/** The owner signature request bound to one intent (A-13 … A-15). */
export interface ApprovalInfo {
  approval_id: string;
  typed_data_hash: string;
  expires_at: string;
}

export interface AgentGate {
  verdict: string;
  reason_codes: string[];
  capacity: { before: Capacity; after: Capacity };
  steps: GateStep[];
  determination_id: string;
  intent_id: string;
  order_id: string;
  execution_id: string;
  audit_uri: string;
  tx_hash: string | null;
  status: string;
  approval?: ApprovalInfo | null;
  findings: PreconditionFinding[];
}

export interface AgentTrace {
  reply: string;
  parse: { message: string; payee: string | null; amount: string | null; source: string };
  gate: AgentGate;
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 120_000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: {
        accept: "application/json",
        authorization: `Bearer ${TOKEN}`,
        ...(init.body ? { "content-type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`${path}: HTTP ${res.status}${text ? ` — ${text.slice(0, 180)}` : ""}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export function getAgentState(): Promise<AgentState> {
  return request<AgentState>("/v1/agent/state");
}

export function runAgent(message: string): Promise<AgentTrace> {
  return request<AgentTrace>("/v1/agent/run", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export interface EnvelopePayload {
  execution_id: string;
  envelope: Record<string, unknown>;
}

/** The signed Rigorix audit envelope for one governed run (the artifact the server wrote). */
export function getEnvelope(executionId: string): Promise<EnvelopePayload> {
  return request<EnvelopePayload>(`/v1/agent/envelope/${encodeURIComponent(executionId)}`, {}, 20_000);
}

export interface TrailItem {
  execution_id: string;
  sequence: number | null;
  timestamp: string;
  prev_hash: string | null;
  template_id: string;
  envelope: Record<string, unknown>;
}

export interface TrailRecord {
  event: string;
  intent_id: string;
  occurred_at: string;
}

/**
 * The chained governed executions, oldest first, each with its signed envelope, plus the
 * Authority's approval decisions (requested / signed / declined), which precede any execution.
 */
export function getTrail(): Promise<{ items: TrailItem[]; records: TrailRecord[] }> {
  return request<{ items: TrailItem[]; records: TrailRecord[] }>("/v1/agent/trail", {}, 20_000);
}

/** Delete the governed-run envelopes (demo control: start a fresh trail). */
export function clearTrail(): Promise<{ cleared: number }> {
  return request<{ cleared: number }>("/v1/agent/trail/clear", { method: "POST" }, 20_000);
}

/**
 * Stage a scenario. `reset: false` (page mount) changes only the cap/threshold and never deletes
 * approvals or today's holds; `reset: true` is the explicit "apply & reset" control.
 */
export function setWorld(cap: number, threshold?: number, reset = true): Promise<AgentState> {
  return request<AgentState>("/v1/agent/world", {
    method: "POST",
    body: JSON.stringify({
      cap,
      ...(threshold === undefined ? {} : { threshold }),
      reset,
    }),
  });
}

export interface AuthorityPayee {
  key: string;
  name: string;
  address: string;
  status: "active" | "frozen" | "unknown" | string;
}

export interface AuthorityState {
  check: string;
  authority_path: string;
  payees: AuthorityPayee[];
}

/** The operator's dispatch-time authority, read from the file the precondition itself reads. */
export function getAuthority(): Promise<AuthorityState> {
  return request<AuthorityState>("/v1/agent/authority", {}, 20_000);
}

export function setAuthority(payee: string, status: "active" | "frozen"): Promise<AuthorityState> {
  return request<AuthorityState>("/v1/agent/authority", {
    method: "POST",
    body: JSON.stringify({ payee, status }),
  });
}

export interface ApprovalGrant {
  approval_id: string;
  granted: boolean;
  events: string[];
  capacity: Capacity;
}

/** Submit the owner's signature for the intent's open request. Capacity is reserved on success. */
export function approveIntent(
  intentId: string,
  signatureHex: string,
  approvalId?: string,
): Promise<ApprovalGrant> {
  return request<ApprovalGrant>("/v1/agent/approve", {
    method: "POST",
    body: JSON.stringify({
      intent_id: intentId,
      signature_hex: signatureHex,
      ...(approvalId ? { approval_id: approvalId } : {}),
    }),
  });
}

export interface ReleaseGate {
  verdict: string;
  steps: GateStep[];
  capacity: { before: Capacity; after: Capacity };
  intent_id: string;
  order_id: string;
  tx_hash: string | null;
  execution_id: string;
  audit_uri: string;
  status: string;
  findings: PreconditionFinding[];
}

export interface ReleaseResponse {
  gate: ReleaseGate;
  refusal: { message: string; broadcast: boolean; findings: PreconditionFinding[] } | null;
}

/** Dispatch the approved intent — the moment the dispatch-time precondition runs. */
export function releaseIntent(intentId: string): Promise<ReleaseResponse> {
  return request<ReleaseResponse>("/v1/agent/release", {
    method: "POST",
    body: JSON.stringify({ intent_id: intentId }),
  });
}

export interface RejectResponse {
  approval_id: string;
  intent_id: string;
  rejected: boolean;
  events: string[];
  capacity: Capacity;
}

/** Decline the open request: the approval is closed and nothing is sent. */
export function rejectIntent(intentId: string, approvalId?: string): Promise<RejectResponse> {
  return request<RejectResponse>("/v1/agent/reject", {
    method: "POST",
    body: JSON.stringify({
      intent_id: intentId,
      ...(approvalId ? { approval_id: approvalId } : {}),
    }),
  });
}
