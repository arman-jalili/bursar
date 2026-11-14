/**
 * The engine strip — which enforcement engine is answering, and the number that proves it.
 *
 * A logo is a claim. This is a reading: the engine's own name, version, API version and anchor
 * head, plus the round-trip that produced them, refreshed while the page is open. When the engine
 * is down the strip says so in red — a status surface that only renders success is decoration.
 */

import { useEffect, useState } from "react";
import { ENGINE_STATUS_URL, fetchEngineStatus, type EngineStatus } from "../engine";

const POLL_MS = 10_000;

function short(value: string | null | undefined, head = 10, tail = 4): string {
  if (!value) return "—";
  return value.length <= head + tail + 1 ? value : `${value.slice(0, head)}…${value.slice(-tail)}`;
}

export function EngineStrip() {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let alive = true;
    const poll = async (): Promise<void> => {
      const answer = await fetchEngineStatus();
      if (!alive) return;
      setStatus(answer);
      setCheckedAt(new Date().toLocaleTimeString());
    };
    void poll();
    const timer = window.setInterval(() => void poll(), POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const reachable = status?.reachable === true;
  const anchorHead = status?.anchor && typeof status.anchor === "object" ? status.anchor.head : null;

  const copyRaw = async (): Promise<void> => {
    const text = JSON.stringify(status?.raw ?? status, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setShowRaw(true); // no clipboard permission: show it so it can still be selected by hand
    }
  };

  return (
    <section className={`engine-strip ${reachable ? "engine-up" : "engine-down"}`} aria-live="polite">
      <div className="engine-left">
        <span className="engine-dot" aria-hidden="true" />
        <strong className="engine-label">ENGINE</strong>
        {status === null ? (
          <span className="engine-muted">asking {ENGINE_STATUS_URL}…</span>
        ) : reachable ? (
          <>
            <span className="engine-name">{status.name ?? "unnamed"}</span>
            <span className="engine-muted">
              engine <b>{status.engine_version ?? "?"}</b> · api{" "}
              <b>{status.api_version ?? "?"}</b> · anchor head{" "}
              <code title={anchorHead ?? ""}>{short(anchorHead)}</code> · integrity{" "}
              <b>{status.history_integrity ?? "?"}</b>
            </span>
          </>
        ) : (
          <>
            <span className="engine-name">unreachable</span>
            <span className="engine-muted">
              {status.error ?? "no error reported"} · checked {checkedAt ?? "—"}
            </span>
          </>
        )}
      </div>

      <div className="engine-right">
        {status?.latency_ms != null && (
          <span className={`engine-latency ${reachable ? "" : "engine-latency-bad"}`}>
            {status.latency_ms} ms
          </span>
        )}
        <button type="button" className="engine-btn" onClick={() => void copyRaw()}>
          {copied ? "copied ✓" : "copy raw"}
        </button>
        <button
          type="button"
          className="engine-btn"
          aria-expanded={showRaw}
          onClick={() => setShowRaw((open) => !open)}
        >
          raw {showRaw ? "▴" : "▾"}
        </button>
        <a className="engine-btn" href={ENGINE_STATUS_URL} target="_blank" rel="noreferrer">
          open ↗
        </a>
      </div>

      {showRaw && (
        <pre className="engine-raw">{JSON.stringify(status?.raw ?? status, null, 2)}</pre>
      )}
    </section>
  );
}