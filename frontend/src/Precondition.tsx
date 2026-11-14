// The second capability: the dispatch-time precondition.
//
// The scenario this page makes visible: a payment above the threshold needs the owner's
// signature. The owner signs, capacity is reserved, and the release is dispatched — but the
// operator's authority is checked again immediately before the broadcast. If the payee was frozen
// in between, Rigorix refuses the step and records why on a signed envelope. No transaction exists.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  approveIntent,
  getAgentState,
  getAuthority,
  releaseIntent,
  runAgent,
  setAuthority as changeAuthority,
  setWorld,
  type AgentState,
  type AgentTrace,
  type ApprovalGrant,
  type AuthorityState,
  type PreconditionFinding,
  type ReleaseResponse,
} from "./agentApi";
import { CapacityBar, GateCard, Trail, VerifyPanel, money, short } from "./Gate";
import { EXPLORER_URL, tokenUrl, txUrl } from "./explorer";
import { DEMO_OWNER_KEY } from "./api";

type Message =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "agent"; text: string; trace?: AgentTrace };

let seq = 0;
const nextId = () => `p${(seq += 1)}`;

const SCENARIO_CAP = 30;
const SCENARIO_THRESHOLD = 15;

function stageOf(authority: AuthorityState | null, name: string) {
  return authority?.payees.find((payee) => payee.name === name)?.status ?? "unknown";
}

function FindingRows({ findings }: { findings: PreconditionFinding[] }) {
  return (
    <div className="gate-findings">
      {findings.map((finding) => (
        <div key={finding.precondition_id} className={`gate-finding ${finding.outcome}`}>
          <div className="gate-finding-head">
            <span className="gate-finding-id">{finding.precondition_id}</span>
            <span className="gate-finding-outcome">{finding.outcome}</span>
            <span className="gate-finding-exit">exit {finding.exit_code ?? "—"}</span>
          </div>
          <p className="gate-finding-summary">{finding.summary}</p>
          <div className="gate-finding-meta">
            <span>check {short(finding.check_digest)}</span>
            <span>authority {short(finding.authority_digest)}</span>
            <span>checked {new Date(finding.checked_at).toLocaleTimeString("de-AT")}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function RefusalResult({ result }: { result: ReleaseResponse }) {
  const { gate, refusal } = result;
  const findings = refusal?.findings.length ? refusal.findings : gate.findings;

  return (
    <article className="gate-card deny gate-release">
      <header className="gate-card-head">
        <span className="gate-verdict deny">STOPPED AT DISPATCH</span>
        <span className="gate-amount">no payment</span>
        <span className="gate-payee">approval revoked by the operator</span>
      </header>
      <p className="gate-reply">
        The owner approved. Capacity was reserved. Then Rigorix asked the operator's authority again
        — right before the broadcast — and the payee was frozen. The step never ran.
      </p>

      <FindingRows findings={findings.length ? findings : []} />

      <ol className="gate-steps">
        {gate.steps.map((step) => (
          <li key={step.name} className={step.ok ? "ok" : "no"}>
            <span className="gate-step-mark">{step.ok ? "✓" : "✕"}</span>
            <span className="gate-step-name">{step.name}</span>
            <span className="gate-step-detail">{step.detail}</span>
          </li>
        ))}
      </ol>

      <div className="gate-capacity">
        <div className="gate-capacity-row">
          <span>free {money(gate.capacity.after.headroom)}</span>
          <span>
            committed {money(gate.capacity.after.committed)} · reserved{" "}
            {money(gate.capacity.after.reserved)}
          </span>
        </div>
        <CapacityBar capacity={gate.capacity.after} />
      </div>

      {gate.execution_id ? (
        <div className="gate-refusal-verify">
          <span className="gate-refusal-stamp">signed refusal · {short(gate.execution_id)}</span>
          <span className="gate-refusal-hint">
            a transaction was signed, but nothing was broadcast — verify the envelope below
          </span>
          {gate.tx_hash ? (
            <span className="gate-refusal-hint">
              signed hash {short(gate.tx_hash)} · not on chain, so the explorer has no transaction
            </span>
          ) : null}
          <VerifyPanel executionId={gate.execution_id} />
        </div>
      ) : null}
    </article>
  );
}

function SuccessResult({ result }: { result: ReleaseResponse }) {
  return (
    <article className="gate-card allow gate-release">
      <header className="gate-card-head">
        <span className="gate-verdict allow">RELEASED</span>
        <span className="gate-amount">broadcast</span>
        <span className="gate-payee">the precondition passed</span>
      </header>
      <p className="gate-reply">
        The owner approved, and at dispatch time the payee was still active. Rigorix ran the governed
        step and the transaction was broadcast.
      </p>
      <ol className="gate-steps">
        {result.gate.steps.map((step) => (
          <li key={step.name} className={step.ok ? "ok" : "no"}>
            <span className="gate-step-mark">{step.ok ? "✓" : "✕"}</span>
            <span className="gate-step-name">{step.name}</span>
            <span className="gate-step-detail">{step.detail}</span>
          </li>
        ))}
      </ol>
      <footer className="gate-card-foot">
        {result.gate.tx_hash ? (
          <a
            className="gate-tx-link"
            href={txUrl(result.gate.tx_hash) ?? undefined}
            target="_blank"
            rel="noreferrer"
          >
            tx {short(result.gate.tx_hash)} on chain ↗
          </a>
        ) : null}
        <span>execution {short(result.gate.execution_id)}</span>
      </footer>
    </article>
  );
}

function ApprovalCard({
  trace,
  authority,
  onFinished,
}: {
  trace: AgentTrace;
  authority: AuthorityState | null;
  onFinished: () => void;
}) {
  const approval = trace.gate.approval;
  const [stage, setStage] = useState<"idle" | "signing" | "dispatching" | "done">("idle");
  const [grant, setGrant] = useState<ApprovalGrant | null>(null);
  const [result, setResult] = useState<ReleaseResponse | null>(null);
  const [error, setError] = useState("");
  const status = trace.parse.payee ? stageOf(authority, trace.parse.payee) : "unknown";

  if (!approval) return null;

  const run = async () => {
    setError("");
    setStage("signing");
    try {
      const { Wallet } = await import("ethers");
      const wallet = new Wallet(DEMO_OWNER_KEY);
      const signature = wallet.signingKey.sign(approval.typed_data_hash).serialized;
      const granted = await approveIntent(trace.gate.intent_id, signature);
      setGrant(granted);
      setStage("dispatching");
      const released = await releaseIntent(trace.gate.intent_id);
      setResult(released);
      setStage("done");
      onFinished();
    } catch (err) {
      setError((err as Error).message.slice(0, 200));
      setStage("idle");
    }
  };

  return (
    <div className="gate-approval">
      <div className="gate-approval-head">
        <span className="gate-approval-tag">signature request</span>
        <span className="gate-approval-digest" title={approval.typed_data_hash}>
          digest {short(approval.typed_data_hash)}
        </span>
      </div>
      <p className="gate-approval-copy">
        {money(trace.parse.amount)} to {trace.parse.payee ?? "this payee"} is above the approval
        threshold. The owner signs; the operator authority is checked again at dispatch.
      </p>
      <div className="gate-approval-row">
        <button
          className="gate-approve-btn"
          onClick={() => void run()}
          disabled={stage === "signing" || stage === "dispatching"}
        >
          {stage === "signing"
            ? "signing…"
            : stage === "dispatching"
              ? "releasing through Rigorix…"
              : result
                ? "approve & release again"
                : "approve & release"}
        </button>
        <span className={`gate-authority-pill ${status}`}>
          payee is {status} at dispatch
        </span>
      </div>
      {grant ? (
        <div className="gate-approval-grant">
          signature verified · capacity reserved {money(grant.capacity.reserved)} of{" "}
          {money(grant.capacity.cap)}
        </div>
      ) : null}
      {error ? <div className="gate-verify-bad">{error}</div> : null}
      {result ? (
        result.refusal ? <RefusalResult result={result} /> : <SuccessResult result={result} />
      ) : null}
    </div>
  );
}

export function Precondition() {
  const [state, setState] = useState<AgentState | null>(null);
  const [authority, setAuthority] = useState<AuthorityState | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [cap, setCap] = useState(String(SCENARIO_CAP));
  const [threshold, setThreshold] = useState(String(SCENARIO_THRESHOLD));
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [trailVersion, setTrailVersion] = useState(0);
  const thread = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const staged = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const [next, auth] = await Promise.all([getAgentState(), getAuthority()]);
      setState(next);
      setAuthority(auth);
    } catch (err) {
      setNotice(`The gate is not answering: ${(err as Error).message}`);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      // Set the stage once: cap 30, threshold 15. A €20 payment needs the owner's signature.
      if (!staged.current) {
        staged.current = true;
        try {
          const next = await setWorld(SCENARIO_CAP, SCENARIO_THRESHOLD);
          setState(next);
          setCap(next.capacity.cap);
        } catch {
          // The refresh below surfaces the real error.
        }
      }
      await refresh();
    })();
  }, [refresh]);

  useEffect(() => {
    thread.current?.scrollTo({ top: thread.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busyRef.current) return;
    busyRef.current = true;
    setMessages((all) => [...all, { id: nextId(), role: "user", text: trimmed }]);
    setInput("");
    setBusy(true);
    setNotice(null);
    try {
      const trace = await runAgent(trimmed);
      setMessages((all) => [...all, { id: nextId(), role: "agent", text: trace.reply, trace }]);
      setState((current) =>
        current ? { ...current, capacity: trace.gate.capacity.after } : current,
      );
      if (trace.gate.execution_id) setTrailVersion((value) => value + 1);
    } catch (err) {
      setMessages((all) => [
        ...all,
        { id: nextId(), role: "agent", text: `The run failed: ${(err as Error).message}` },
      ]);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, []);

  const applyWorld = useCallback(async () => {
    const capValue = Number(cap);
    const thresholdValue = Number(threshold);
    if (!Number.isFinite(capValue) || capValue <= 0 || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setNotice(null);
    try {
      const next = await setWorld(capValue, Number.isFinite(thresholdValue) ? thresholdValue : capValue);
      setState(next);
      setMessages((all) => [
        ...all,
        {
          id: nextId(),
          role: "agent",
          text: `A new world: €${next.capacity.cap} cap, approval above €${threshold}. Pay something above the threshold.`,
        },
      ]);
    } catch (err) {
      setNotice(`The world could not be set: ${(err as Error).message}`);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [cap, threshold]);

  const toggle = useCallback(
    async (key: string, status: "active" | "frozen") => {
      try {
        const next = await changeAuthority(key, status);
        setAuthority(next);
        setNotice(null);
      } catch (err) {
        setNotice(`The authority could not be changed: ${(err as Error).message}`);
      }
    },
    [],
  );

  const capacity = state?.capacity;

  return (
    <div className="gate">
      <header className="gate-top">
        <div className="gate-brand">
          <span className="gate-mark">b</span>
          <span className="gate-word">bursar</span>
          <span className="gate-capability">dispatch precondition</span>
        </div>
        <nav className="gate-nav" aria-label="Capabilities">
          <a className="gate-nav-link" href="#capacity">
            capacity
          </a>
          <a className="gate-nav-link active" href="#precondition">
            precondition
          </a>
        </nav>
        <div className="gate-meta">
          {state?.chain.usdc ? (
            <a
              className="gate-explorer-link"
              href={tokenUrl(state.chain.usdc) ?? EXPLORER_URL}
              target="_blank"
              rel="noreferrer"
              title={`USDC token on the explorer · treasury ${state.chain.treasury}`}
            >
              USDC wallet ↗
            </a>
          ) : null}
          <a className="gate-explorer-link" href={EXPLORER_URL} target="_blank" rel="noreferrer">
            explorer ↗
          </a>
          <span className="gate-live">
            <i className="dot" /> live
          </span>
          <span className="gate-chain">anvil ·{" "}
            {authority?.payees.filter((payee) => payee.status === "frozen").length ?? 0} frozen</span>
        </div>
      </header>

      <main className="gate-wrap">
        <section className="gate-hero">
          <div>
            <div className="eyebrow">
              <span className="line" />
              An approval is not a durable grant
            </div>
            <h1>
              Approve. <em>Then watch it be re-checked.</em>
            </h1>
            <p className="gate-lede">
              The owner's signature gets a payment to the edge of the network. Rigorix runs the
              operator's own check immediately before the broadcast — after the approval, inside the
              governed step. Freeze the payee after signing and the payment stops with a signed
              finding. Nothing is broadcast.
            </p>
          </div>
          <div className="gate-hero-capacity">
            <div className="gate-hero-label">
              <span>Free capacity</span>
              <span>live</span>
            </div>
            <div className="gate-hero-number">{money(capacity?.headroom)}</div>
            <div className="gate-hero-sub">
              of {money(capacity?.cap)} · committed {money(capacity?.committed)} · reserved{" "}
              {money(capacity?.reserved)}
            </div>
            {capacity ? <CapacityBar capacity={capacity} /> : <div className="gate-bar" />}
          </div>
        </section>

        <div className="gate-grid">
          <section className="gate-chat">
            <div className="gate-thread" ref={thread} aria-live="polite">
              {messages.length === 0 ? (
                <div className="gate-empty">
                  <p className="gate-empty-title">Ask for something above €{threshold}.</p>
                  <p className="gate-empty-copy">
                    The agent writes a real proposal, capacity fits, but the amount is above the
                    approval threshold — so the owner is asked to sign. Then freeze the payee and
                    release.
                  </p>
                  <div className="gate-chips">
                    {["pay the energy bill 20", "pay the energy bill 12"].map((example) => (
                      <button
                        key={example}
                        className="gate-chip"
                        onClick={() => void send(example)}
                        disabled={busy}
                      >
                        {example}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {messages.map((message) =>
                message.role === "user" ? (
                  <div key={message.id} className="gate-msg user">
                    <span className="gate-who">you</span>
                    <p>{message.text}</p>
                  </div>
                ) : (
                  <div key={message.id} className="gate-msg agent">
                    <span className="gate-who">agent</span>
                    {message.trace ? (
                      <>
                        <GateCard trace={message.trace} />
                        {message.trace.gate.verdict === "escalate" ? (
                          <ApprovalCard
                            trace={message.trace}
                            authority={authority}
                            onFinished={() => {
                              setTrailVersion((value) => value + 1);
                              void refresh();
                            }}
                          />
                        ) : null}
                      </>
                    ) : (
                      <p className="gate-text">{message.text}</p>
                    )}
                  </div>
                ),
              )}

              {busy ? (
                <div className="gate-msg agent">
                  <span className="gate-who">agent</span>
                  <p className="gate-thinking">proposing · checking the cap · asking the gate…</p>
                </div>
              ) : null}
            </div>

            {notice ? <div className="gate-notice">{notice}</div> : null}

            <form
              className="gate-input"
              onSubmit={(event) => {
                event.preventDefault();
                void send(input);
              }}
            >
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="pay the energy bill 20"
                aria-label="Payment instruction"
                disabled={busy}
              />
              <button className="gate-send" type="submit" disabled={busy || !input.trim()}>
                run →
              </button>
            </form>
          </section>

          <aside className="gate-world">
            <h2>The world</h2>
            <p className="gate-world-sub">
              Cap and approval threshold. Reset the day. Then ask again.
            </p>

            <div className="gate-field-pair">
              <label className="gate-field">
                <span>Capacity</span>
                <div className="gate-field-row">
                  <span className="gate-currency">€</span>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={cap}
                    onChange={(event) => setCap(event.target.value)}
                    disabled={busy}
                    aria-label="Capacity in euro"
                  />
                </div>
              </label>
              <label className="gate-field">
                <span>Approval above</span>
                <div className="gate-field-row">
                  <span className="gate-currency">€</span>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={threshold}
                    onChange={(event) => setThreshold(event.target.value)}
                    disabled={busy}
                    aria-label="Approval threshold in euro"
                  />
                </div>
              </label>
            </div>
            <button className="gate-apply wide" onClick={() => void applyWorld()} disabled={busy}>
              apply &amp; reset
            </button>

            <div className="gate-authority">
              <div className="gate-authority-head">
                <span>operator authority</span>
                <span className="gate-authority-path" title={authority?.authority_path}>
                  outside the repo
                </span>
              </div>
              <p className="gate-authority-copy">
                The check Rigorix runs at dispatch reads this file. Freezing a payee here does not
                touch any approval.
              </p>
              {authority?.payees.map((payee) => (
                <div key={payee.key} className="gate-authority-row">
                  <div className="gate-authority-name">
                    <span>{payee.name}</span>
                    <span className={`gate-payee-status ${payee.status}`}>{payee.status}</span>
                  </div>
                  <button
                    className={`gate-toggle ${payee.status}`}
                    onClick={() =>
                      void toggle(payee.key, payee.status === "active" ? "frozen" : "active")
                    }
                  >
                    {payee.status === "active" ? "freeze" : "reactivate"}
                  </button>
                </div>
              ))}
            </div>

            <div className="gate-note">
              A refusal at dispatch is signed evidence, not an error. The order stays signed; the
              transaction is never broadcast.
            </div>

            <div className="gate-llm">
              <i className={state?.llm.ready ? "dot" : "dot off"} />
              {state?.llm.ready ? `parsed by ${state.llm.model}` : "local parser (no LLM key)"}
            </div>
          </aside>
        </div>
        <Trail refresh={trailVersion} />
      </main>
    </div>
  );
}
