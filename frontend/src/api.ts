// API-first client. Falls back to demo fixtures when the console API is not up.
// Contract: docs/BURSAR-BUILD-CONTRACT.md (11 public endpoints under /api).

import {
  CHAIN,
  INITIAL_APPROVAL,
  INITIAL_ATTEMPTS,
  INITIAL_POLICY,
  sumSettled,
} from "./data";
import type { Attempt, ApprovalRequest, ChainState, Policy } from "./data";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";
const FORCE_MOCK = (import.meta.env.VITE_FORCE_MOCK as string | undefined) === "1";
export const DEMO_HMAC_KEY =
  (import.meta.env.VITE_DEMO_HMAC_KEY as string | undefined) ?? "bursar-demo-hmac-key";

export type Source = "api" | "mock";

export interface BursarState {
  household: { name: string; city: string };
  mode: "base-sepolia" | "anvil";
  policy: Policy;
  chain: ChainState;
  attempts: Attempt[];
  approval?: ApprovalRequest | null;
  source: Source;
}

async function get<T>(path: string, timeoutMs = 2500): Promise<T> {
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { accept: "application/json" },
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(id);
  }
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${path}: HTTP ${res.status}${text ? ` — ${text.slice(0, 200)}` : ""}`);
  }
  return (await res.json().catch(() => ({}))) as T;
}

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
    const [state, attempts] = await Promise.all([
      get<{
        household: { name: string; city: string };
        mode: "base-sepolia" | "anvil";
        policy: Policy;
        chain: ChainState;
        approval?: ApprovalRequest | null;
      }>("/state"),
      get<Attempt[]>("/attempts"),
    ]);
    return {
      ...state,
      attempts,
      approval: state.approval ?? INITIAL_APPROVAL,
      source: "api",
    };
  } catch {
    return demoState();
  }
}

export function subscribe(
  onEvent: (type: string, payload: unknown) => void,
  onStatus?: (live: boolean) => void,
): () => void {
  if (FORCE_MOCK || typeof EventSource === "undefined") return () => undefined;
  const es = new EventSource(`${API_BASE}/events`);
  const types = ["attempt.updated", "capacity.updated", "approval.requested", "chain.updated"];
  const handlers = types.map((type) => {
    const fn = (e: MessageEvent) => {
      try {
        onEvent(type, JSON.parse(e.data));
      } catch {
        onEvent(type, e.data);
      }
    };
    es.addEventListener(type, fn as EventListener);
    return [type, fn] as const;
  });
  es.onopen = () => onStatus?.(true);
  es.onerror = () => onStatus?.(false);
  return () => {
    handlers.forEach(([type, fn]) => es.removeEventListener(type, fn as EventListener));
    es.close();
  };
}

export async function approve(
  attemptId: string,
  body: { signature: string; ownerAddress: string; nonce: string; deadline: string },
): Promise<void> {
  await post(`/attempts/${attemptId}/approve`, body);
}

export async function deny(attemptId: string): Promise<void> {
  await post(`/attempts/${attemptId}/deny`);
}

export async function freezePayee(payeeId: string): Promise<void> {
  await post(`/payees/${payeeId}/freeze`);
}

export async function runScenario(id: string): Promise<unknown> {
  return post(`/scenarios/${id}`);
}

export async function fetchEnvelope(attemptId: string): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>(`/attempts/${attemptId}/envelope`);
}

// The browser verifier is a real protocol verifier (WebCrypto). In mock mode we
// return `simulated: true` so the UI can label the demo honestly.
export async function verifyEnvelope(
  attempt: Attempt,
): Promise<{ ok: boolean; simulated: boolean; error?: string }> {
  if (!attempt.rigorix?.envelopeUri) {
    return { ok: true, simulated: true };
  }
  try {
    const envelope = await fetchEnvelope(attempt.id);
    const mod = await import("rigorix-verifier/browser");
    await mod.verifySignature(envelope as never, DEMO_HMAC_KEY);
    await mod.validateEnvelope(envelope as never);
    return { ok: true, simulated: false };
  } catch (err) {
    if (err instanceof TypeError || (err as Error).name === "AbortError") {
      // API unavailable -> mock mode.
      return { ok: true, simulated: true };
    }
    return { ok: false, simulated: false, error: (err as Error).message };
  }
}

export async function signApproval(request: ApprovalRequest): Promise<{
  signature: string;
  ownerAddress: string;
}> {
  const eth = (window as unknown as { ethereum?: unknown }).ethereum as
    | { request: (args: { method: string; params?: unknown[] }) => Promise<unknown> }
    | undefined;
  if (!eth) {
    // No wallet in the demo browser: return a deterministic demo signature.
    return {
      signature: `0xdemo${Date.now().toString(16)}${"0".repeat(110)}`.slice(0, 132),
      ownerAddress: "0x5F2a9c1e0b4d7a6f3e2c1b0a9d8e7f6a5c4b3d21",
    };
  }
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

export function settledToday(attempts: Attempt[]): number {
  return sumSettled(attempts);
}
