/**
 * The inspector panel — the page's own network log, with a copy-pasteable reproduction per call.
 *
 * This is the answer to "is this a fake UI?": the panel is not a mock, it is the log of what the
 * page actually asked for, including the calls that failed. Every row can become a `curl` the
 * reviewer runs against the same service.
 */

import { useEffect, useState } from "react";
import { DEMO_OWNER_KEY } from "../api";
import {
  asCurl,
  clearCalls,
  getCalls,
  isInspectorInstalled,
  subscribe,
  type RecordedCall,
} from "../inspector";

// The demo token is public by design (it authenticates the demo owner, not a person). It is read
// from the same place the API client reads it so a `curl` copy is a real reproduction.
const TOKEN =
  (import.meta.env.VITE_OWNER_TOKEN as string | undefined) ?? "demo-owner-token";

function statusClass(call: RecordedCall): string {
  if (call.outcome === "pending") return "call-pending";
  if (call.outcome === "error") return "call-error";
  return "call-ok";
}

function CallRow({ call }: { call: RecordedCall }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(asCurl(call, TOKEN));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setOpen(true);
    }
  };

  return (
    <li className={`call ${statusClass(call)}`}>
      <div className="call-head">
        <button type="button" className="call-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          <span className="call-method">{call.method}</span>
          <span className="call-path" title={call.url}>
            {call.path}
          </span>
          <span className="call-status">{call.status ?? (call.error ? "ERR" : "…")}</span>
          <span className="call-duration">{call.durationMs} ms</span>
        </button>
        <button type="button" className="call-copy" onClick={() => void copy()}>
          {copied ? "copied ✓" : "curl"}
        </button>
      </div>

      {open && (
        <div className="call-body">
          {call.correlationId && (
            <p className="call-meta">
              correlation id <code>{call.correlationId}</code>
            </p>
          )}
          {call.error && <p className="call-meta call-meta-bad">network: {call.error}</p>}
          <p className="call-meta">request</p>
          <pre>{call.requestBody ?? "— (no body)"}</pre>
          <p className="call-meta">response {call.status ?? ""}</p>
          <pre>{call.responseBody ?? "— (no body)"}</pre>
        </div>
      )}
    </li>
  );
}

export function InspectorPanel() {
  const [open, setOpen] = useState(false);
  const [calls, setCalls] = useState<RecordedCall[]>(getCalls());

  useEffect(() => subscribe(() => setCalls([...getCalls()])), []);

  const failures = calls.filter((call) => call.outcome === "error").length;

  return (
    <aside className={`inspector ${open ? "inspector-open" : ""}`}>
      <button
        type="button"
        className="inspector-trigger"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="inspector-title">CALL INSPECTOR</span>
        <span className="inspector-count">{calls.length} calls</span>
        {failures > 0 && <span className="inspector-failures">{failures} failed</span>}
        <span className="inspector-chevron">{open ? "▾" : "▴"}</span>
      </button>

      {open && (
        <div className="inspector-body">
          <p className="inspector-note">
            Every request this page made, including failures —{" "}
            {isInspectorInstalled() ? "captured by wrapping window.fetch" : "capture not installed"}.
            Paste a row into a terminal to get the same bytes.
          </p>
          <div className="inspector-actions">
            <button type="button" className="engine-btn" onClick={() => clearCalls()}>
              clear
            </button>
            <span className="inspector-hint">
              demo owner key in bundle: {`${DEMO_OWNER_KEY.slice(0, 10)}…`} (public test key)
            </span>
          </div>
          {calls.length === 0 ? (
            <p className="inspector-note">No calls yet — interact with the page.</p>
          ) : (
            <ul className="call-list">
              {calls.map((call) => (
                <CallRow key={call.id} call={call} />
              ))}
            </ul>
          )}
        </div>
      )}
    </aside>
  );
}