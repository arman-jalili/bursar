import { useMemo, useState } from "react";

type Experiment = "scam" | "split" | "dentist" | "normal";
type Verdict = "ALLOWED" | "REFUSED" | "ESCALATED";

interface Outcome {
  outcome: Verdict;
  rule: string;
  why: string;
  unsafe?: boolean;
}

interface Config {
  dailyCap: number;
  perPayeeCap: number;
  threshold: number;
  quarantine: boolean;
  newPayeeRule: boolean;
  freezeWien: boolean;
  freezeDentist: boolean;
}

const DEFAULT: Config = {
  dailyCap: 500,
  perPayeeCap: 400,
  threshold: 100,
  quarantine: true,
  newPayeeRule: true,
  freezeWien: false,
  freezeDentist: false,
};

const EXPERIMENTS: { id: Experiment; label: string; amount: number; blurb: string }[] = [
  { id: "scam", label: "Scam invoice", amount: 84.2, blurb: "A changed bank detail, below the signature line. The bank-detail guard is the only lever." },
  { id: "split", label: "Split invoice", amount: 90, blurb: "The fifth €90 invoice. €476.30 is already committed to the split." },
  { id: "dentist", label: "New payee", amount: 240, blurb: "A new dentist, above the €100 line." },
  { id: "normal", label: "Normal bill", amount: 84.2, blurb: "A known payee, inside the caps." },
];

const eur = (n: number) =>
  new Intl.NumberFormat("de-AT", { style: "currency", currency: "EUR" }).format(n);

function simulate(exp: Experiment, c: Config): Outcome {
  const amount =
    exp === "scam" ? 84.2 : exp === "split" ? 90 : exp === "dentist" ? 240 : 84.2;
  const baseCommitted = exp === "split" ? 476.3 : exp === "normal" ? 32.1 : 116.3;
  const isNew = exp === "dentist";
  const bankMismatch = exp === "scam";
  const frozen = (exp === "scam" && c.freezeWien) || (exp === "dentist" && c.freezeDentist);

  if (frozen) {
    return {
      outcome: "REFUSED",
      rule: "payee_frozen",
      why: "The payee is frozen. Dispatch re-reads the live state and refuses before any money moves.",
    };
  }

  if (bankMismatch && c.quarantine) {
    return {
      outcome: "REFUSED",
      rule: "bank_digest_mismatch",
      why: "The presented bank digest differs from the verified one. The guard is on, so the payment is refused.",
    };
  }

  if (baseCommitted + amount > c.dailyCap) {
    return {
      outcome: "REFUSED",
      rule: "daily_cap",
      why: `${eur(baseCommitted + amount)} would exceed the ${eur(c.dailyCap)} daily cap.`,
    };
  }

  if (amount > c.perPayeeCap) {
    return {
      outcome: "REFUSED",
      rule: "per_payee_cap",
      why: `${eur(amount)} is above the ${eur(c.perPayeeCap)} per-payee cap.`,
    };
  }

  if (isNew && c.newPayeeRule) {
    return {
      outcome: "ESCALATED",
      rule: "new_payee",
      why: "A new payee needs your signature before the first payment. The agent cannot sign it.",
    };
  }

  if (amount > c.threshold) {
    return {
      outcome: "ESCALATED",
      rule: "above_threshold",
      why: `${eur(amount)} is above your ${eur(c.threshold)} signature line.`,
    };
  }

  return {
    outcome: "ALLOWED",
    rule: bankMismatch ? "bank_digest_mismatch_disabled" : "all_rules_pass",
    why: bankMismatch
      ? "The guard is off. The altered bank details would be used and the money would move."
      : "Every rule passes. The agent would pay it.",
    unsafe: bankMismatch,
  };
}

function noteFor(exp: Experiment, result: Outcome, runs: number): string {
  if (result.unsafe) return "This is how a scam gets paid. Would you sleep with this lever off?";
  if (exp === "split" && result.outcome === "ALLOWED")
    return "Six small invoices just became one big hole. That is why the cap exists.";
  if (exp === "dentist" && result.outcome === "ALLOWED")
    return "No signature. The agent just paid a new dentist on its own.";
  if (result.outcome === "REFUSED")
    return "The invoice never changed. The rule did the work.";
  if (result.outcome === "ESCALATED")
    return "Not refused — handed to you. The agent cannot finish this alone.";
  if (runs > 1) return "Same world, same result. Determinism is the point.";
  return "Move a lever. Run it again. Watch the stamp change.";
}

export function Lab() {
  const [exp, setExp] = useState<Experiment>("scam");
  const [config, setConfig] = useState<Config>(DEFAULT);
  const [result, setResult] = useState<Outcome>(() => simulate("scam", DEFAULT));
  const [previous, setPrevious] = useState<Outcome | null>(null);
  const [runs, setRuns] = useState(0);

  const selected = EXPERIMENTS.find((e) => e.id === exp)!;
  const note = useMemo(() => noteFor(exp, result, runs), [exp, result, runs]);

  const set = <K extends keyof Config>(key: K, value: Config[K]) =>
    setConfig((c) => ({ ...c, [key]: value }));

  const run = () => {
    setPrevious(result);
    setResult(simulate(exp, config));
    setRuns((r) => r + 1);
  };

  const choose = (id: Experiment) => {
    setExp(id);
    setPrevious(null);
    setResult(simulate(id, config));
    setRuns(0);
  };

  const reset = () => {
    setConfig(DEFAULT);
    setExp("scam");
    setResult(simulate("scam", DEFAULT));
    setPrevious(null);
    setRuns(0);
  };

  const changed =
    previous &&
    (previous.outcome !== result.outcome || previous.rule !== result.rule);

  return (
    <section className="lab" aria-label="The control room">
      <div className="lab-card">
        <div className="lab-head">
          <div>
            <div className="eyebrow">
              <span className="line" />
              The control room
            </div>
            <h2>Change the world. Re-run the payment.</h2>
            <p>
              A sandbox for the same decision logic. Move a lever, run the experiment again, and
              watch the same invoice get through — or get refused.
            </p>
            <span className="lab-badge">sandbox · not the live ledger</span>
          </div>
          <span className="funky-note" style={{ fontSize: 20, maxWidth: 220 }}>
            Same invoice. New world. Watch the stamp.
          </span>
        </div>

        <div className="lab-grid">
          <div className="lab-controls">
            <div className="exp-tabs">
              {EXPERIMENTS.map((e) => (
                <button
                  key={e.id}
                  className={`exp-tab${exp === e.id ? " active" : ""}`}
                  onClick={() => choose(e.id)}
                >
                  {e.label}
                </button>
              ))}
            </div>
            <p className="lever-note" style={{ marginBottom: 14 }}>
              {selected.blurb}
            </p>

            <div className="lever">
              <div className="lever-top">
                <span className="lever-name">Daily cap</span>
                <span className="lever-val">{eur(config.dailyCap)}</span>
              </div>
              <input
                type="range"
                min={100}
                max={1000}
                step={10}
                value={config.dailyCap}
                onChange={(e) => set("dailyCap", Number(e.target.value))}
                aria-label="Daily cap"
              />
              <div className="lever-note">Total committed + this payment must stay under this.</div>
            </div>

            <div className="lever">
              <div className="lever-top">
                <span className="lever-name">Per-payee cap</span>
                <span className="lever-val">{eur(config.perPayeeCap)}</span>
              </div>
              <input
                type="range"
                min={50}
                max={1000}
                step={10}
                value={config.perPayeeCap}
                onChange={(e) => set("perPayeeCap", Number(e.target.value))}
                aria-label="Per-payee cap"
              />
              <div className="lever-note">No single payee above this per day.</div>
            </div>

            <div className="lever">
              <div className="lever-top">
                <span className="lever-name">Owner signature over</span>
                <span className="lever-val">{eur(config.threshold)}</span>
              </div>
              <input
                type="range"
                min={0}
                max={500}
                step={10}
                value={config.threshold}
                onChange={(e) => set("threshold", Number(e.target.value))}
                aria-label="Owner signature threshold"
              />
              <div className="lever-note">Above this line, the payment waits for you.</div>
            </div>

            <div className="switch-row">
              <div>
                <div className="s-name">Bank-detail change → refuse</div>
                <div className="s-note">The scam guard. Turn it off and re-run the scam.</div>
              </div>
              <button
                className={`switch${config.quarantine ? " on" : ""}`}
                onClick={() => set("quarantine", !config.quarantine)}
                aria-pressed={config.quarantine}
                aria-label="Bank-detail change guard"
              />
            </div>
            <div className="switch-row">
              <div>
                <div className="s-name">New payees need a signature</div>
                <div className="s-note">The dentist rule. Turn it off and re-run the new payee.</div>
              </div>
              <button
                className={`switch${config.newPayeeRule ? " on" : ""}`}
                onClick={() => set("newPayeeRule", !config.newPayeeRule)}
                aria-pressed={config.newPayeeRule}
                aria-label="New payees need a signature"
              />
            </div>
            <div className="switch-row">
              <div>
                <div className="s-name">Freeze Wien Energie</div>
                <div className="s-note">Freeze the payee and re-run the scam or normal bill.</div>
              </div>
              <button
                className={`switch${config.freezeWien ? " on" : ""}`}
                onClick={() => set("freezeWien", !config.freezeWien)}
                aria-pressed={config.freezeWien}
                aria-label="Freeze Wien Energie"
              />
            </div>
            <div className="switch-row">
              <div>
                <div className="s-name">Freeze the dentist</div>
                <div className="s-note">Approved at T0, frozen at Tn — re-run the dentist.</div>
              </div>
              <button
                className={`switch${config.freezeDentist ? " on" : ""}`}
                onClick={() => set("freezeDentist", !config.freezeDentist)}
                aria-pressed={config.freezeDentist}
                aria-label="Freeze the dentist"
              />
            </div>

            <div className="lab-actions">
              <button className="btn forest" onClick={run}>
                {runs === 0 ? "Run experiment →" : "Repeat experiment →"}
              </button>
              <button className="btn ghost" onClick={reset}>
                Reset levers
              </button>
            </div>
          </div>

          <div className="lab-result" aria-live="polite">
            <div className="mono" style={{ color: "#8F877A", letterSpacing: ".1em" }}>
              RESULT · {selected.label.toUpperCase()} · {eur(selected.amount)}
            </div>
            <div className={`outcome ${result.outcome.toLowerCase()}`}>{result.outcome}</div>
            <div className="rule-code">{result.rule}</div>
            <div className="why">{result.why}</div>

            <div className="compare">
              {changed && previous ? (
                <>
                  Before: <b>{previous.outcome}</b> by <b>{previous.rule}</b>. Now:{" "}
                  <b>{result.outcome}</b> by <b>{result.rule}</b>. The invoice did not change. The
                  rule did.
                </>
              ) : runs > 0 ? (
                <>Same world, same result. That is determinism — not luck.</>
              ) : (
                <>Now move a lever and run it again.</>
              )}
            </div>

            <div className="funky-note" style={{ fontSize: 20, maxWidth: "100%" }}>
              {note}
            </div>

            <div className="mono" style={{ color: "#8F877A", fontSize: 10 }}>
              simulation · the live payment still goes through Rigorix
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
