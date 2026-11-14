import type { Attempt, VerifyState } from "../data";
import { envelopePreview, formatAmount, shortHash, timeLabel } from "../data";
import type { Source } from "../api";

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

function consoleEvidenceRecord(attempt: Attempt): Record<string, unknown> {
  return {
    envelope_id: attempt.evidenceId,
    event_type: attempt.evidenceEvent,
    occurred_at: attempt.evidenceAt ?? attempt.createdAt,
    result: attempt.evidenceResult,
    anchor_tx: attempt.anchorTx ?? null,
    subject: {
      invoice_id: attempt.invoiceId,
      payee: attempt.payee.name,
      payee_address: attempt.payee.address || null,
      amount_usdc: attempt.amountUsdc,
      status: attempt.status,
    },
    verification: `GET /v1/console/evidence/${attempt.evidenceId}/verify`,
    note: "Console evidence record — the verdict is the Evidence service's, proxied by the console.",
  };
}

export function EvidenceDrawer({ attempt, source, verified, onClose, onVerify, onFlip }: Props) {
  if (!attempt) return null;
  const status = statusOf(attempt);
  const hasConsoleEvidence = Boolean(attempt.evidenceId);
  const hasEnvelope = Boolean(attempt.rigorix?.envelopeUri) || hasConsoleEvidence;
  const json = JSON.stringify(
    hasConsoleEvidence
      ? consoleEvidenceRecord(attempt)
      : hasEnvelope
        ? envelopePreview(attempt)
        : consoleRecord(attempt),
    null,
    2,
  );

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
            {hasConsoleEvidence
              ? "Evidence envelope (console record)"
              : hasEnvelope
                ? "Rigorix envelope"
                : "Console refusal record (no engine envelope)"}
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
            {attempt.evidenceId ? (
              <>
                evidence <b>{attempt.evidenceId}</b> · <b>{attempt.evidenceEvent}</b> ·{" "}
                <b>{attempt.evidenceResult}</b>
                <br />
              </>
            ) : null}
            {attempt.rigorix?.envelopeHash ? (
              <>
                envelope <b>{shortHash(attempt.rigorix.envelopeHash, 8, 6)}</b>
                <br />
              </>
            ) : null}
            {attempt.anchorTx ?? attempt.rigorix?.anchoredTx ? (
              <>
                anchor <b>{shortHash(attempt.anchorTx ?? attempt.rigorix?.anchoredTx ?? "", 8, 6)}</b>
                <br />
              </>
            ) : null}
            consequence <b>{attempt.status === "refused" ? "none — no transaction" : "settled / pending"}</b>
          </div>
        </div>

        <div className="evidence-foot">
          <span>
            {source === "api"
              ? hasConsoleEvidence
                ? "evidence envelope from the console API"
                : "demo envelope — this surface has no raw envelope"
              : "demo envelope"}
          </span>
          <span>HMAC · chain · browser verify</span>
        </div>
      </aside>
    </>
  );
}
