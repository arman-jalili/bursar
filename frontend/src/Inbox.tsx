/**
 * The whole demo: one page, one list, and one drawer that explains what Rigorix did.
 *
 * The organising idea: Rigorix is the product, so the page is built around what the engine did —
 * executed, stopped, or waiting — and every row expands into the evidence for that claim. Nothing
 * on this screen is a picture of a product: each line comes from an endpoint, and the drawer names
 * which one.
 *
 * Deliberately absent: a "lab", a "story rail", a marketing masthead, a simulation. A local
 * simulation rendered next to live data makes the live data look simulated, which is the opposite
 * of the point.
 */

import { useCallback, useEffect, useState } from "react";
import {
  approveConsole,
  dispatchIntent,
  loadState,
  signApproval,
  type BursarState,
} from "./api";
import { formatAmount, leftToday, type Attempt } from "./data";
import { InspectorPanel } from "./components/InspectorPanel";
import { ENGINE_STATUS_URL, fetchEngineStatus, type EngineStatus } from "./engine";

type Phase = "idle" | "signing" | "dispatching" | "done" | "error";

function short(value: string | undefined, head = 10, tail = 6): string {
  if (!value) return "—";
  return value.length <= head + tail + 1 ? value : `${value.slice(0, head)}…${value.slice(-tail)}`;
}

/** One sentence per row, in the engine's terms: executed, stopped, or waiting on a human. */
function verdict(attempt: Attempt): { label: string; tone: "ok" | "stop" | "wait" | "idle" } {
  if (attempt.settlement?.txHash) return { label: "executed", tone: "ok" };
  if (attempt.decision && attempt.decision.allow === false) return { label: "stopped", tone: "stop" };
  if (attempt.status === "pending_approval") return { label: "waiting for you", tone: "wait" };
  if (attempt.status === "refused") return { label: "stopped", tone: "stop" };
  return { label: "proposed", tone: "idle" };
}

function reasonLine(attempt: Attempt): string {
  const decision = attempt.decision;
  if (!decision) return "no determination yet";
  const code = decision.rule ?? "—";
  const text = decision.reason ?? (decision.allow ? "permitted" : "refused");
  return `${code} · ${text}`;
}

export function Inbox() {
  const [state, setState] = useState<BursarState | null>(null);
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [next, engineStatus] = await Promise.all([loadState(), fetchEngineStatus()]);
    setState(next);
    setEngine(engineStatus);
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 8000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const attempts = state?.attempts ?? [];
  const live = state?.source === "api";
  const open = attempts.find((attempt) => attempt.id === selected) ?? null;

  const act = async (attempt: Attempt): Promise<void> => {
    setPhase("signing");
    setNote(null);
    try {
      if (attempt.approvalId) {
        const signed = await signApproval({
          approvalId: attempt.approvalId,
          attemptId: attempt.id,
          invoiceId: attempt.invoiceId,
          payee: attempt.payee,
          amountUsdc: attempt.amountUsdc,
          eip712: {
            domain: "Bursar",
            chainId: "31337",
            verifyingContract: state?.chain.router ?? "",
            intentDigest: attempt.id,
          },
        } as never);
        setPhase("dispatching");
        await approveConsole(attempt.approvalId, signed.signature);
      }
      setPhase("dispatching");
      if (attempt.id) await dispatchIntent(attempt.id);
      setPhase("done");
      setNote("Rigorix executed the governed step. See the execution block below.");
      await refresh();
    } catch (exc) {
      setPhase("error");
      setNote(exc instanceof Error ? exc.message : String(exc));
    }
  };

  return (
    <div className="rig-page">
      <header className="rig-head">
        <div className="rig-brand">
          <span className={`rig-engine-dot ${engine?.reachable ? "up" : "down"}`} />
          <div>
            <div className="rig-engine-name">
              Rigorix <span className="rig-engine-sub">governed execution</span>
            </div>
            <div className="rig-engine-meta">
              {engine?.reachable ? (
                <>
                  engine <b>{engine.engine_version}</b> · api <b>{engine.api_version}</b> ·{" "}
                  {engine.latency_ms} ms · evidence{" "}
                  <b>{engine.history_integrity ?? "—"}</b>
                </>
              ) : (
                <>unreachable — {engine?.error ?? "no answer"} </>
              )}
            </div>
          </div>
        </div>
        <div className="rig-household">
          <div className="rig-hh-name">{state?.household.name ?? "—"}</div>
          <div className="rig-hh-meta">
            cap {formatAmount(state?.policy.dailyCapUsdc ?? "0")} · left{" "}
            {formatAmount(String(leftToday(state?.policy ?? { dailyCapUsdc: "0", perPayeeCapUsdc: "0", approvalThresholdUsdc: "0", allowlist: [], quarantineOnBankChange: false, frozenPayeeIds: [] }, attempts)))}
          </div>
        </div>
      </header>

      <main className="rig-main">
        <div className="rig-section-head">
          <h1>Bills</h1>
          <span className={`rig-source ${live ? "live" : "mock"}`}>
            {live ? "live console" : "offline fixture"}
          </span>
        </div>
        <p className="rig-lede">
          Each row is one payment. <b>Rigorix</b> either executed it inside a governed step, stopped
          it before anything moved, or is waiting for your signature. Click a row to see the evidence.
        </p>

        <ul className="rig-list">
          {attempts.length === 0 && <li className="rig-empty">No bills yet.</li>}
          {attempts.map((attempt) => {
            const v = verdict(attempt);
            return (
              <li key={attempt.id}>
                <button
                  type="button"
                  className={`rig-row rig-row-${v.tone}`}
                  onClick={() => {
                    setSelected(attempt.id);
                    setPhase("idle");
                    setNote(null);
                  }}
                >
                  <span className="rig-row-payee">{attempt.payee.name}</span>
                  <span className="rig-row-amount">{formatAmount(attempt.amountUsdc)}</span>
                  <span className={`rig-chip rig-chip-${v.tone}`}>{v.label}</span>
                  <span className="rig-row-reason">{reasonLine(attempt)}</span>
                  <span className="rig-row-go">→</span>
                </button>
              </li>
            );
          })}
        </ul>

        <p className="rig-proposer">
          The proposer is a process, not a button: <code>python scripts/agent.py</code> reads unpaid
          invoices and posts proposals. This page never invents one.
        </p>
      </main>

      {open && (
        <aside className="rig-sheet" aria-label="Payment detail">
          <button type="button" className="rig-sheet-close" onClick={() => setSelected(null)}>
            close ✕
          </button>

          <section className="rig-block">
            <h2>1 · The bill</h2>
            <p className="rig-big">{formatAmount(open.amountUsdc)}</p>
            <p>{open.payee.name}</p>
            <p className="rig-dim">invoice {short(open.invoiceId, 8, 4)} · proposed {open.createdAt}</p>
          </section>

          <section className="rig-block">
            <h2>2 · What decided</h2>
            <p className={`rig-verdict rig-verdict-${verdict(open).tone}`}>
              {open.decision?.allow === false
                ? "STOPPED"
                : open.decision?.allow
                  ? "PERMITTED"
                  : "UNDECIDED"}
            </p>
            <ul className="rig-facts">
              <li>
                <span>rule</span>
                <b>{open.decision?.rule ?? "—"}</b>
              </li>
              <li>
                <span>reason</span>
                <b>{open.decision?.reason ?? "—"}</b>
              </li>
              <li>
                <span>decided by</span>
                <b>{open.decision?.source ?? "—"}</b>
              </li>
            </ul>
          </section>

          <section className="rig-block">
            <h2>3 · Rigorix execution</h2>
            <ul className="rig-facts">
              <li>
                <span>execution</span>
                <b>{short(open.rigorix?.executionId, 12, 6)}</b>
              </li>
              <li>
                <span>evidence</span>
                <b>{open.rigorix?.envelopeUri ?? open.rigorix?.envelopeHash ?? "—"}</b>
              </li>
              <li>
                <span>tx</span>
                <b>{open.settlement?.txHash ?? "not executed"}</b>
              </li>
              <li>
                <span>block</span>
                <b>{open.settlement?.block ?? "—"}</b>
              </li>
              <li>
                <span>engine</span>
                <b>
                  {engine?.name ?? "—"} {engine?.engine_version ?? ""}
                </b>
              </li>
            </ul>
            {!open.settlement?.txHash && (
              <p className="rig-dim">
                No transaction exists for this row. That is the point: a stopped payment leaves
                nothing on chain.
              </p>
            )}
          </section>

          <section className="rig-block rig-block-action">
            <h2>4 · Your move</h2>
            {open.status === "pending_approval" ? (
              <button
                type="button"
                className="rig-primary"
                disabled={phase === "signing" || phase === "dispatching"}
                onClick={() => void act(open)}
              >
                {phase === "signing"
                  ? "signing…"
                  : phase === "dispatching"
                    ? "asking Rigorix to execute…"
                    : `Sign and pay ${formatAmount(open.amountUsdc)}`}
              </button>
            ) : open.decision?.allow === false ? (
              <p className="rig-dim">
                Nothing to do. The engine stopped this before any money moved — that is the
                guarantee, not an error.
              </p>
            ) : (
              <p className="rig-dim">
                {open.settlement?.txHash
                  ? "Already executed by Rigorix."
                  : "Waiting on the proposer or the engine."}
              </p>
            )}
            {note && <p className="rig-note">{note}</p>}
          </section>

          <p className="rig-source-line">
            data: {live ? "console-api" : "offline fixture"} · engine:{" "}
            <a href={ENGINE_STATUS_URL} target="_blank" rel="noreferrer">
              /v1/engine/status
            </a>
          </p>
        </aside>
      )}

      <InspectorPanel />
    </div>
  );
}