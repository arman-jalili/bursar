/**
 * The call inspector — every request the page makes, recorded, with a copyable curl.
 *
 * Why this exists: the honest question about any demo UI is "is this real, or is it a picture of a
 * product?" A screenshot cannot answer that. A panel listing the exact HTTP calls the page made
 * can, because the reviewer can paste one into a terminal and get the same bytes back.
 *
 * How it stays honest: it wraps `window.fetch` once, at import time, and records *everything* —
 * including the failures and the requests that never reached a server. Filtering interesting calls
 * out of the log would turn the panel into another claim instead of evidence.
 */

export type CallOutcome = "pending" | "ok" | "error";

export interface RecordedCall {
  id: number;
  method: string;
  url: string;
  /** Path only, which is what a reader recognises. */
  path: string;
  startedAt: number;
  durationMs: number;
  status: number | null;
  outcome: CallOutcome;
  requestBody: string | null;
  responseBody: string | null;
  /** The server's correlation id, when the error envelope carried one. */
  correlationId: string | null;
  /** Set when the request never produced a response (network failure, abort, CORS). */
  error: string | null;
}

const MAX_CALLS = 200;
const BODY_LIMIT = 24_000;

let nextId = 1;
const calls: RecordedCall[] = [];
const listeners = new Set<() => void>();
let installed = false;

function notify(): void {
  for (const listener of listeners) listener();
}

function clip(value: string): string {
  return value.length > BODY_LIMIT ? `${value.slice(0, BODY_LIMIT)}\n… truncated` : value;
}

function prettifyBody(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  try {
    return clip(JSON.stringify(JSON.parse(trimmed), null, 2));
  } catch {
    return clip(trimmed);
  }
}

function record(call: RecordedCall): void {
  calls.unshift(call);
  if (calls.length > MAX_CALLS) calls.length = MAX_CALLS;
  notify();
}

function patch(call: RecordedCall, changes: Partial<RecordedCall>): void {
  Object.assign(call, changes);
  notify();
}

function readCorrelationId(text: string | null): string | null {
  if (!text) return null;
  try {
    const parsed = JSON.parse(text) as { correlation_id?: unknown };
    return typeof parsed.correlation_id === "string" ? parsed.correlation_id : null;
  } catch {
    return null;
  }
}

/** Wrap `window.fetch` once. Safe to call repeatedly; only the first call installs. */
export function installInspector(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  const original = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const started = performance.now();
    const request = input instanceof Request ? input : null;
    const url = request ? request.url : String(input);
    const method = (init?.method ?? request?.method ?? "GET").toUpperCase();
    let path = url;
    try {
      const parsed = new URL(url, window.location.origin);
      path = `${parsed.pathname}${parsed.search}`;
    } catch {
      /* a relative or opaque URL: the raw string is the best path we have */
    }

    const call: RecordedCall = {
      id: nextId++,
      method,
      url,
      path,
      startedAt: started,
      durationMs: 0,
      status: null,
      outcome: "pending",
      requestBody: null,
      responseBody: null,
      correlationId: null,
      error: null,
    };

    const rawBody = typeof init?.body === "string" ? init.body : null;
    if (rawBody) call.requestBody = prettifyBody(rawBody);
    record(call);

    try {
      const response = await original(input, init);
      const durationMs = Math.round((performance.now() - started) * 10) / 10;

      // Cloning keeps the page's own consumption untouched; a reader that cannot be cloned (a
      // stream) simply leaves the body empty rather than breaking the call it was observing.
      let text: string | null = null;
      try {
        text = await response.clone().text();
      } catch {
        text = null;
      }

      patch(call, {
        durationMs,
        status: response.status,
        outcome: response.ok ? "ok" : "error",
        responseBody: text ? prettifyBody(text) : null,
        correlationId: readCorrelationId(text),
      });
      return response;
    } catch (exc) {
      patch(call, {
        durationMs: Math.round((performance.now() - started) * 10) / 10,
        outcome: "error",
        error: exc instanceof Error ? exc.message : String(exc),
      });
      throw exc;
    }
  };
}

/** True when the inspector has replaced `fetch` (the panel says so rather than implying it). */
export function isInspectorInstalled(): boolean {
  return installed;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getCalls(): RecordedCall[] {
  return calls;
}

/** A runnable reproduction. The token is the demo's, which is exactly why it can be published. */
export function asCurl(call: RecordedCall, token: string | null): string {
  const parts = [`curl -sS -X ${call.method} '${call.url}'`];
  if (token) parts.push(`  -H 'authorization: Bearer ${token}'`);
  if (call.requestBody) {
    parts.push("  -H 'content-type: application/json'");
    const oneLine = JSON.stringify(JSON.parse(call.requestBody));
    parts.push(`  -d '${oneLine}'`);
  }
  return parts.join(" \\\n");
}

export function clearCalls(): void {
  calls.length = 0;
  notify();
}