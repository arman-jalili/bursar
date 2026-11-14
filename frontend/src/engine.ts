/**
 * The engine status client. Nothing clever: one GET, the whole body, no default that pretends.
 *
 * `fetchEngineStatus` never throws. A strip that disappears when the network blips is worse than
 * one that says "unreachable" — the absence of a reading is a reading.
 */

const CONSOLE_BASE =
  (import.meta.env.VITE_CONSOLE_API_URL as string | undefined) ?? "http://127.0.0.1:8000";

export const ENGINE_STATUS_URL = `${CONSOLE_BASE}/v1/engine/status`;

export interface EngineStatus {
  reachable: boolean;
  base_url?: string;
  endpoint?: string;
  latency_ms?: number;
  name?: string;
  engine_version?: string;
  api_version?: string;
  anchor?: { head?: string | null; id?: string | null } | null;
  history_integrity?: string;
  capabilities?: string[];
  schemas?: string[];
  error?: string;
  raw?: Record<string, unknown>;
}

export async function fetchEngineStatus(): Promise<EngineStatus> {
  try {
    const response = await fetch(ENGINE_STATUS_URL, {
      headers: { accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      return { reachable: false, error: `HTTP ${response.status} from ${ENGINE_STATUS_URL}` };
    }
    const body = (await response.json()) as EngineStatus;
    return body;
  } catch (exc) {
    return {
      reachable: false,
      error: exc instanceof Error ? exc.message : String(exc),
    };
  }
}