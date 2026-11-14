import type { Attempt, Policy } from "../data";
import { formatAmount, leftToday, sumCommitted } from "../data";

export type ActiveRule = "bank-change" | "daily-cap" | "freeze" | "new-payee" | null;

interface Props {
  policy: Policy;
  attempts: Attempt[];
  activeRule: ActiveRule;
  onToggleQuarantine: () => void;
  onViewEvidence?: () => void;
}

export function Constitution({
  policy,
  attempts,
  activeRule,
  onToggleQuarantine,
  onViewEvidence,
}: Props) {
  const committed = sumCommitted(attempts);
  const left = leftToday(policy, attempts);
  const cap = Number(policy.dailyCapUsdc);
  const pct = cap > 0 ? Math.min(100, (left / cap) * 100) : 0;
  const frozen = policy.frozenPayeeIds.length;
  const dailyActive = activeRule === "daily-cap";
  const bankActive = activeRule === "bank-change";

  return (
    <aside className="constitution">
      <div className="panel-head">
        <h2>The Constitution</h2>
        <span className="lock" title="Only the owner can edit these rules">
          🔒 owner-only
        </span>
      </div>
      <div className="panel-sub">The rules that decide every payment.</div>
      <span className="funky-note" style={{ fontSize: 16, margin: "0 16px 12px" }}>
        The agent cannot edit these. That&apos;s the point.
      </span>

      <div className={`clause${dailyActive ? " active" : ""}`}>
        <div className="clause-top">
          <span className="clause-name">Daily cap</span>
          <span className="clause-val">{formatAmount(policy.dailyCapUsdc)}</span>
        </div>
        <div className="mini-bar">
          <i style={{ width: `${pct}%` }} />
        </div>
        <div className="clause-note">
          {formatAmount(String(committed))} committed · {formatAmount(String(left))} left.
          {dailyActive ? " This clause refused the split invoice." : ""}
        </div>
      </div>

      <div className="clause">
        <div className="clause-top">
          <span className="clause-name">Per-payee cap</span>
          <span className="clause-val">{formatAmount(policy.perPayeeCapUsdc)}</span>
        </div>
        <div className="clause-note">No single payee above this per day.</div>
      </div>

      <div className="clause">
        <div className="clause-top">
          <span className="clause-name">Owner signature over</span>
          <span className="clause-val">{formatAmount(policy.approvalThresholdUsdc)}</span>
        </div>
        <div className="clause-note">Anything above this line waits for you.</div>
      </div>

      <div className={`clause${activeRule === "new-payee" ? " active" : ""}`}>
        <div className="clause-top">
          <span className="clause-name">New payees</span>
          <span className="toggle" aria-hidden="true" />
        </div>
        <div className="clause-note">
          {activeRule === "new-payee"
            ? "The €240 dentist is waiting for your signature under this clause."
            : "Require an owner signature before the first payment."}
        </div>
      </div>

      <div className={`clause${bankActive ? " active" : ""}`}>
        <div className="clause-top">
          <span className="clause-name">Bank-detail change</span>
          <button
            type="button"
            className={`toggle${policy.quarantineOnBankChange ? "" : " off"}`}
            onClick={onToggleQuarantine}
            aria-label={`Bank-detail change quarantine is ${
              policy.quarantineOnBankChange ? "on" : "off"
            }`}
            aria-pressed={policy.quarantineOnBankChange}
          />
        </div>
        <div className="clause-note">
          {policy.quarantineOnBankChange ? (
            <>
              Quarantine the payee and refuse the invoice.
              {bankActive ? <b> This clause refused the €1,240.00 “Wien Energie” invoice.</b> : null}
            </>
          ) : (
            "Off — a changed bank detail would be allowed. Not recommended."
          )}
        </div>
      </div>

      <div className={`clause${activeRule === "freeze" ? " active" : ""}`}>
        <div className="clause-top">
          <span className="clause-name">Frozen payees</span>
          <span className="clause-val">{frozen}</span>
        </div>
        <div className="clause-note">
          {frozen > 0
            ? "A frozen payee is ineligible at the next dispatch, even if it was approved."
            : "Freeze a payee and the next dispatch is refused."}
        </div>
      </div>

      {activeRule && onViewEvidence ? (
        <button className="rules-evidence" onClick={onViewEvidence}>
          View the evidence for this rule →
        </button>
      ) : null}

      <div className="constitution-foot">
        <span>
          Edited 2m ago by <b>Mira</b>
        </span>
        <span>v3</span>
      </div>
    </aside>
  );
}
