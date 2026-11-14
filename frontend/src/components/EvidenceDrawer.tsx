import { useEffect, useState } from "react";
import type { Attempt, VerifyState } from "../data";
import { envelopePreview, formatAmount, shortHash, timeLabel } from "../data";
import { fetchEnvelope, type Source } from "../api";

interface Props {
  attempt: Attempt | null;
  source: Source;
  verified: VerifyState;
  onClose: () => void;
  onVerify: (attempt: Attempt) => void;
  onFlip: (attempt: Attempt) => void;
}

function statusOf(attempt: Attempt): { cls: string; label: string } {
  if (attempt.status === "settled") return { cls: "paid", label: "✓ paid" };
  if (attempt.status === "pending_approval") return { cls: "wait", label: "◷ waiting" };
  if (attempt.status === "refused")
    return attempt.decision?.rule === "daily_cap"
      ? { cls: "cap", label: "◼ refused · cap" }
      : { cls: "refused", label: "✕ refused" };
  return { cls: "wait", label: attempt.status };
}

function consoleRecord(attempt: Attempt): Record<string, unknown> {
  return {
    attempt_id: attempt.id,
    invoice_id: attempt.invoiceId,
    payee: {
      id: attempt.payee.id,
      name: attempt.payee.name,
      address: attempt.payee.address,
    },
    amount_usdc: attempt.amountUsdc,
    rule: attempt.decision?.rule,
    reason: attempt.decision?.reason,
    source: attempt.decision?.source,
    decided_at: attempt.createdAt,
    consequence: "no transaction",
    evidence: "console record — not a Rigorix engine envelope",
  };
}

export function EvidenceDrawer({ attempt, source, verified, onClose, onVerify, onFlip }: Props) {
  const [liveJson, setLiveJson] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLiveJson(null);
    if (!attempt || source !== "api" || !attempt.rigorix?.envelopeUri) {
      return () => {
        alive = false;
      };
    }
    fetchEnvelope(attempt.id)
      .then((envelope) => {
        if (alive) setLiveJson(JSON.stringify(envelope, null, 2));
      })
      .catch(() => {
        // Keep the representative preview when the API is unavailable.
      });
    return () => {
      alive = false;
    };
  }, [attempt?.id, source]);

  if (!attempt) return null;
  const status = statusOf(attempt);
  const hasEnvelope = Boolean(attempt.rigorix?.envelopeUri);
  const json =
    liveJson ??
    JSON.stringify(hasEnvelope ? envelopePreview(attempt) : consoleRecord(attempt), null, 2);

  return (
    <>
      <div className="evidence-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-label="Receipt evidence">
        <div className="evidence-head">
          <div>
            <div className="k">
              {hasEnvelope ? "Signed receipt" : "Console record"} · {timeLabel(attempt.createdAt)}
            </div>
            <h3>{attempt.payee.name}</h3>
          </div>
          <button onClick={onClose} aria-label="Close receipt">
            ×
          </button>
        </div>

        <div className="evidence-body">
          <div className="evidence-status">
            <span className={`status ${status.cls}`}>{status.label}</span>
            <span className="mono" style={{ color: "var(--muted)" }}>
              {attempt.invoiceId}
            </span>
          </div>
          <div className="evidence-amount">{formatAmount(attempt.amountUsdc)}</div>
          <p className="evidence-reason">{attempt.narrative}</p>
          {attempt.decision?.rule ? (
            <span className="evidence-rule">
              {attempt.decision.rule} · {attempt.decision.source}
            </span>
          ) : null}

          <div className="mono" style={{ color: "var(--muted)", margin: "2px 0 6px" }}>
            {hasEnvelope ? "Rigorix envelope" : "Console refusal record (no engine envelope)"}
          </div>
          <pre className="evidence-json">{json}</pre>

          {hasEnvelope ? (
            <div className="evidence-actions">
              <button
                className={`verify${verified === "ok" ? " ok" : verified === "bad" ? " bad" : ""}`}
                onClick={() => onVerify(attempt)}
              >
                {verified === "ok" ? "Verified ✓" : verified === "bad" ? "Tampered ✕" : "Verify"}
              </button>
              <button className="flip" onClick={() => onFlip(attempt)}>
                Flip a byte
              </button>
            </div>
          ) : null}

          <div className="evidence-tx">
            {attempt.settlement?.txHash ? (
              <>
                settle tx <b>{shortHash(attempt.settlement.txHash, 8, 6)}</b> · block{" "}
                <b>{attempt.settlement.block?.toLocaleString("en-US")}</b>
                <br />
              </>
            ) : null}
            {attempt.rigorix?.envelopeHash ? (
              <>
                envelope <b>{shortHash(attempt.rigorix.envelopeHash, 8, 6)}</b>
                <br />
              </>
            ) : null}
            {attempt.rigorix?.anchoredTx ? (
              <>
                anchor <b>{shortHash(attempt.rigorix.anchoredTx, 8, 6)}</b>
                <br />
              </>
            ) : null}
            consequence <b>{attempt.status === "refused" ? "none — no transaction" : "settled / pending"}</b>
          </div>
        </div>

        <div className="evidence-foot">
          <span>
            {source === "api"
              ? liveJson
                ? "live envelope from rigorix-server"
                : "envelope preview — live fetch unavailable"
              : "demo envelope"}
          </span>
          <span>HMAC · chain · browser verify</span>
        </div>
      </aside>
    </>
  );
}
