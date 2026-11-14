import { useCallback, useEffect, useRef, useState } from "react";
import {
  clearTrail,
  getAgentState,
  getEnvelope,
  getTrail,
  runAgent,
  setWorld,
  type AgentState,
  type AgentTrace,
  type Capacity,
  type PreconditionFinding,
  type TrailItem,
} from "./agentApi";
import { EXPLORER_URL, tokenUrl, txUrl } from "./explorer";

type Message =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "agent"; text: string; trace?: AgentTrace };

let seq = 0;
const nextId = () => `m${(seq += 1)}`;

// Demo operator key: the same HMAC Rigorix signs its envelopes with. Public test value.
const RIGORIX_HMAC_KEY =
  (import.meta.env.VITE_RIGORIX_HMAC_KEY as string | undefined) ??
  "bursar-demo-operator-held-evidence-key-4c1f9a";

export const money = (value: string | null | undefined) =>
  value === null || value === undefined ? "—" : `€${value}`;

export function short(hash: string | null | undefined): string {
  if (!hash) return "";
  return `${hash.slice(0, 10)}…${hash.slice(-6)}`;
}

function verdictLabel(verdict: string): { label: string; cls: string } {
  switch (verdict) {
    case "allow":
      return { label: "PAID", cls: "allow" };
    case "deny":
      return { label: "REFUSED", cls: "deny" };
    case "escalate":
      return { label: "NEEDS YOUR APPROVAL", cls: "escalate" };
    case "dispatch_failed":
      return { label: "NOT SENT", cls: "deny" };
    case "refused_at_dispatch":
      return { label: "STOPPED BY RIGORIX", cls: "deny" };
    default:
      return { label: "NOT RUN", cls: "neutral" };
  }
}

/** The step names are the API's; this is the household language the card shows. */
const STEP_LABELS: Record<string, string> = {
  parse: "Understood",
  invoice: "Bill",
  propose: "Proposal",
  capacity: "Spending limit",
  rigorix: "Rigorix",
  chain: "Blockchain",
  approval: "Your signature",
};

export function stepLabel(name: string): string {
  return STEP_LABELS[name] ?? name;
}

const FINDING_TITLES: Record<string, string> = {
  "capacity-available": "The spending limit",
  "payee-authorized": "The operator's payee check",
  "approval-valid": "Your approval",
};

function findingSentence(
  id: string,
  amount: string | null | undefined,
  headroom: string | undefined,
): string {
  if (id === "capacity-available") {
    return amount && headroom
      ? `This payment (${money(amount)}) would take you over your daily limit; ${money(headroom)} is still free.`
      : "This payment would take you over your daily limit.";
  }
  if (id === "payee-authorized") {
    return "This payee is frozen, so the payment was stopped.";
  }
  if (id === "approval-valid") {
    return "The owner's approval is required for this amount.";
  }
  return "Rigorix refused this step.";
}

/** The check that refused, in household language, with the rule and digests kept as evidence. */
export function FindingRows({
  findings,
  amount,
  headroom,
}: {
  findings: PreconditionFinding[];
  amount?: string | null;
  headroom?: string;
}) {
  // Only a check that refused is a finding the reader must act on. The checks that passed before
  // it are still evidence, but rendering them as refusals would say the opposite of what happened.
  const refused = findings.filter((finding) => finding.outcome !== "passed");
  const passed = findings.filter((finding) => finding.outcome === "passed");
  if (refused.length === 0) return null;
  return (
    <div className="gate-findings">
      {refused.map((finding) => (
        <div key={finding.precondition_id} className={`gate-finding ${finding.outcome}`}>
          <div className="gate-finding-head">
            <span className="gate-finding-title">
              {FINDING_TITLES[finding.precondition_id] ?? "Rigorix check"}
            </span>
            <span className="gate-finding-outcome">refused</span>
          </div>
          <p className="gate-finding-summary">
            {findingSentence(finding.precondition_id, amount, headroom)}
          </p>
          <div className="gate-finding-meta">
            <span>rule {finding.precondition_id}</span>
            <span>exit {finding.exit_code ?? "—"}</span>
            <span>check {short(finding.check_digest)}</span>
            <span>authority {short(finding.authority_digest)}</span>
            <span>checked {new Date(finding.checked_at).toLocaleTimeString("de-AT")}</span>
          </div>
        </div>
      ))}
      {passed.length > 0 ? (
        <p className="gate-finding-passed">
          Passed before it:{" "}
          {passed
            .map((finding) => FINDING_TITLES[finding.precondition_id] ?? finding.precondition_id)
            .join(" · ")}
        </p>
      ) : null}
    </div>
  );
}

export function CapacityBar({ capacity }: { capacity: Capacity }) {
  const cap = Number(capacity.cap) || 1;
  const committed = Math.min(100, (Number(capacity.committed) / cap) * 100);
  const reserved = Math.min(100 - committed, (Number(capacity.reserved) / cap) * 100);
  return (
    <div className="gate-bar" aria-hidden="true">
      <i className="committed" style={{ width: `${committed}%` }} />
      <i className="reserved" style={{ width: `${reserved}%` }} />
    </div>
  );
}

function VerifyEnvelope({
  envelope,
  executionId,
}: {
  envelope: Record<string, unknown>;
  executionId: string;
}) {
  const [status, setStatus] = useState<"idle" | "checking" | "ok" | "bad" | "tampered">(
    "idle",
  );
  const [detail, setDetail] = useState("");

  const verify = async () => {
    setStatus("checking");
    setDetail("");
    try {
      const mod = await import("rigorix-verifier/browser");
      await mod.verifySignature(envelope as never, RIGORIX_HMAC_KEY);
      mod.validateEnvelope(envelope as never);
      setStatus("ok");
    } catch (err) {
      setStatus("bad");
      setDetail((err as Error).message.slice(0, 140));
    }
  };

  const flip = async () => {
    const copy = structuredClone(envelope);
    // Change a signed field; the canonical bytes change, the HMAC no longer matches.
    copy.timestamp = `${String(copy.timestamp ?? "")}x`;
    try {
      const mod = await import("rigorix-verifier/browser");
      await mod.verifySignature(copy as never, RIGORIX_HMAC_KEY);
      setStatus("bad");
      setDetail("the modified envelope still verified");
    } catch {
      // The flipped byte is rejected: the status itself turns red.
      setStatus("tampered");
      setDetail("");
    }
  };

  return (
    <div className="gate-verify">
      <div className="gate-verify-row">
        <button
          className={`gate-verify-btn ${status}`}
          onClick={() => void verify()}
          disabled={status === "checking"}
        >
          {status === "checking"
            ? "verifying…"
            : status === "ok"
              ? "Verified in your browser ✓"
              : status === "tampered"
                ? "Tampered ✕ — verify original"
                : status === "bad"
                  ? "Verify failed — retry"
                  : "Verify in browser"}
        </button>
        {status === "ok" ? (
          <button className="gate-tamper" onClick={() => void flip()}>
            Flip a byte
          </button>
        ) : null}
        <span className="gate-verify-key">WebCrypto · HMAC · demo operator key</span>
      </div>
      {status === "tampered" ? (
        <span className="gate-verify-bad">one byte changed — signature rejected</span>
      ) : null}
      {status === "bad" && detail ? <span className="gate-verify-bad">{detail}</span> : null}
      <details className="gate-envelope">
        <summary>signed envelope · {short(executionId)}</summary>
        <pre>{JSON.stringify(envelope, null, 2)}</pre>
      </details>
    </div>
  );
}

export function VerifyPanel({ executionId }: { executionId: string }) {
  const [envelope, setEnvelope] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    getEnvelope(executionId)
      .then((data) => {
        if (alive) setEnvelope(data.envelope);
      })
      .catch((err: Error) => {
        if (alive) setError(err.message.slice(0, 120));
      });
    return () => {
      alive = false;
    };
  }, [executionId]);

  if (!envelope) {
    return (
      <div className="gate-verify">
        <span className="gate-verify-key">
          {error ? `signed envelope unavailable: ${error}` : "loading signed envelope…"}
        </span>
      </div>
    );
  }
  return <VerifyEnvelope envelope={envelope} executionId={executionId} />;
}

export function GateCard({ trace }: { trace: AgentTrace }) {
  const { gate, parse } = trace;
  const verdict = verdictLabel(gate.verdict);
  const after = gate.capacity.after;
  const source = parse.source === "llm" ? "llm" : "local parser";
  // A signed order carries a hash even when the governed step refused to broadcast it. The hash
  // proves what would have been sent; it is not a transaction on chain, so it is never a link.
  const sent = gate.steps.some((step) => step.name === "chain" && step.ok);

  return (
    <article className={`gate-card ${verdict.cls}`}>
      <header className="gate-card-head">
        <span className={`gate-verdict ${verdict.cls}`}>{verdict.label}</span>
        <span className="gate-amount">{money(parse.amount)}</span>
        <span className="gate-payee">{parse.payee ?? "no payee"}</span>
        <span className="gate-parser" title={`Parsed by ${source}`}>
          {source}
        </span>
      </header>

      <p className="gate-reply">{trace.reply}</p>

      <div className="gate-capacity">
        <div className="gate-capacity-row">
          <span>free {money(after.headroom)}</span>
          <span>
            committed {money(after.committed)} · reserved {money(after.reserved)} · cap{" "}
            {money(after.cap)}
          </span>
        </div>
        <CapacityBar capacity={after} />
      </div>

      <ol className="gate-steps">
        {gate.steps
          .filter((step) =>
            ["parse", "invoice", "propose", "rigorix", "chain"].includes(step.name),
          )
          .map((step) => (
          <li key={step.name} className={step.ok ? "ok" : "no"}>
            <span className="gate-step-mark">{step.ok ? "✓" : "✕"}</span>
            <span className="gate-step-name">{stepLabel(step.name)}</span>
            <span className="gate-step-detail">{step.detail}</span>
          </li>
        ))}
      </ol>

      <FindingRows findings={gate.findings} amount={parse.amount} headroom={after.headroom} />

      {gate.execution_id ? <VerifyPanel executionId={gate.execution_id} /> : null}

      <footer className="gate-card-foot">
        {gate.determination_id ? <span>decision record {short(gate.determination_id)}</span> : null}
        {gate.tx_hash && sent ? (
          <a
            className="gate-tx-link"
            href={txUrl(gate.tx_hash) ?? undefined}
            target="_blank"
            rel="noreferrer"
          >
            transaction {short(gate.tx_hash)} ↗
          </a>
        ) : null}
        {gate.tx_hash && !sent ? (
          <span>
            signed transaction {short(gate.tx_hash)}, never sent — no money moved
          </span>
        ) : null}
        {!gate.tx_hash && gate.verdict === "deny" ? (
          <span>No transaction was created — nothing was signed or sent.</span>
        ) : null}
        {!gate.tx_hash && gate.verdict === "dispatch_failed" ? (
          <span>Nothing was signed or sent.</span>
        ) : null}
      </footer>
    </article>
  );
}

export function Trail({ refresh }: { refresh: number }) {
  const [items, setItems] = useState<TrailItem[]>([]);
  const [hashes, setHashes] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [chain, setChain] = useState<{ ok: boolean; broken: number; partial: boolean } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let alive = true;
    getTrail()
      .then(async (data) => {
        if (!alive) return;
        setItems(data.items);
        setSelected((current) =>
          current && data.items.some((item) => item.execution_id === current)
            ? current
            : (data.items[data.items.length - 1]?.execution_id ?? null),
        );
        if (data.items.length === 0) {
          setHashes([]);
          setChain(null);
          return;
        }
        try {
          const mod = await import("rigorix-verifier/browser");
          const computed = await Promise.all(
            data.items.map((item) => mod.envelopeHash(item.envelope as never)),
          );
          const clean = computed.map((hash) => String(hash).replace(/^0x/, ""));
          if (!alive) return;
          setHashes(clean);
          let broken = -1;
          for (let i = 1; i < data.items.length; i += 1) {
            const prev = String(data.items[i].prev_hash ?? "").replace(/^0x/, "");
            if (prev && prev !== clean[i - 1]) {
              broken = i;
              break;
            }
          }
          const partial = broken < 0 && Boolean(data.items[0]?.prev_hash);
          setChain({ ok: broken < 0 && !partial, broken, partial });
        } catch {
          if (alive) {
            setHashes([]);
            setChain(null);
          }
        }
      })
      .catch((err: Error) => {
        if (alive) setError(err.message.slice(0, 120));
      });
    return () => {
      alive = false;
    };
  }, [refresh, version]);

  const selectedIndex = items.findIndex((item) => item.execution_id === selected);
  const selectedItem = selectedIndex >= 0 ? items[selectedIndex] : null;
  const linkStatus = (() => {
    if (!selectedItem) return "";
    if (selectedIndex === 0) {
      return selectedItem.prev_hash ? "predecessor not retained" : "chain start";
    }
    const previous = items[selectedIndex - 1];
    const prev = String(selectedItem.prev_hash ?? "").replace(/^0x/, "");
    const prevHash = String(hashes[selectedIndex - 1] ?? "").replace(/^0x/, "");
    return prev && prev === prevHash
      ? `matches #${previous.sequence ?? selectedIndex}`
      : "does not match";
  })();

  const clear = async () => {
    if (!window.confirm("Delete the governed-run envelopes and start a fresh trail?")) return;
    try {
      await clearTrail();
      setVersion((value) => value + 1);
      setSelected(null);
    } catch (err) {
      setError((err as Error).message.slice(0, 120));
    }
  };

  return (
    <section className="gate-trail">
      <div className="gate-trail-head">
        <div>
          <h2>The trail</h2>
          <p>Every governed run, chained to the one before it. Click one to inspect its envelope.</p>
        </div>
        <div className="gate-trail-actions">
          {chain ? (
            <span
              className={`gate-chain-state ${chain.ok ? "ok" : chain.partial ? "partial" : "bad"}`}
            >
              {chain.ok
                ? `chain intact · ${items.length} execution${items.length === 1 ? "" : "s"}`
                : chain.partial
                  ? `partial chain · predecessor not retained`
                  : `chain broken at #${items[chain.broken]?.sequence ?? chain.broken + 1}`}
            </span>
          ) : null}
          {items.length > 0 ? (
            <button className="gate-trail-clear" onClick={() => void clear()}>
              clear trail
            </button>
          ) : null}
        </div>
      </div>

      {items.length === 0 ? (
        <p className="gate-trail-empty">No governed runs yet. Ask the agent to pay something.</p>
      ) : (
        <div className="gate-trail-seq">
          {items.map((item, index) => (
            <button
              key={item.execution_id}
              className={`gate-trail-item${selected === item.execution_id ? " active" : ""}`}
              onClick={() => setSelected(item.execution_id)}
              title={item.execution_id}
            >
              <span className="gate-trail-n">#{item.sequence ?? index + 1}</span>
              <span className="gate-trail-id">{short(item.execution_id)}</span>
              <span className="gate-trail-hash">{hashes[index] ? short(hashes[index]) : "…"}</span>
              <span className="gate-trail-time">
                {new Date(item.timestamp).toLocaleTimeString("de-AT", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </button>
          ))}
        </div>
      )}

      {selectedItem ? (
        <div className="gate-trail-detail">
          <div className="gate-trail-detail-head">
            <span>execution {short(selectedItem.execution_id)}</span>
            <span>
              prev {selectedItem.prev_hash ? short(String(selectedItem.prev_hash)) : "chain start"} ·{" "}
              <b className={linkStatus === "does not match" ? "bad" : "ok"}>{linkStatus}</b>
            </span>
          </div>
          <VerifyEnvelope
            envelope={selectedItem.envelope}
            executionId={selectedItem.execution_id}
          />
        </div>
      ) : null}
      {error ? <p className="gate-verify-bad">{error}</p> : null}
    </section>
  );
}

export function Gate() {
  const [state, setState] = useState<AgentState | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [cap, setCap] = useState("30");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [trailVersion, setTrailVersion] = useState(0);
  const thread = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const staged = useRef(false);

  const load = useCallback(async () => {
    try {
      const next = await getAgentState();
      setState(next);
      setCap(next.capacity.cap);
    } catch (err) {
      setNotice(`The gate is not answering: ${(err as Error).message}`);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      // This capability's scenario is cap 30 with no approval threshold (every payment inside the
      // cap runs). Set it once per visit so the capacity story stays true after the precondition
      // page has staged its own world.
      if (!staged.current) {
        staged.current = true;
        try {
          const next = await setWorld(30, 30, false);
          setState(next);
          setCap(next.capacity.cap);
        } catch {
          // The refresh below surfaces the real error.
        }
      }
      await load();
    })();
  }, [load]);

  useEffect(() => {
    thread.current?.scrollTo({ top: thread.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busyRef.current) return;
      busyRef.current = true;
      setMessages((all) => [...all, { id: nextId(), role: "user", text: trimmed }]);
      setInput("");
      setBusy(true);
      setNotice(null);
      try {
        const trace = await runAgent(trimmed);
        setMessages((all) => [
          ...all,
          { id: nextId(), role: "agent", text: trace.reply, trace },
        ]);
        setState((current) =>
          current ? { ...current, capacity: trace.gate.capacity.after } : current,
        );
        if (trace.gate.execution_id) setTrailVersion((value) => value + 1);
      } catch (err) {
        setMessages((all) => [
          ...all,
          {
            id: nextId(),
            role: "agent",
            text: `The run failed: ${(err as Error).message}`,
          },
        ]);
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [],
  );

  const applyWorld = useCallback(async () => {
    const value = Number(cap);
    if (!Number.isFinite(value) || value <= 0 || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setNotice(null);
    try {
      const next = await setWorld(value, undefined, true);
      setState(next);
      setMessages((all) => [
        ...all,
        {
          id: nextId(),
          role: "agent",
          text: `A new world: €${next.capacity.cap} capacity, nothing committed. Ask me to pay something.`,
        },
      ]);
    } catch (err) {
      setNotice(`The world could not be set: ${(err as Error).message}`);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [cap]);

  const capacity = state?.capacity;
  const examples = [
    "pay the energy bill 20",
    "pay energy 11",
    "pay the dentist 8",
  ];

  return (
    <div className="gate">
      <header className="gate-top">
        <div className="gate-brand">
          <span className="gate-mark">b</span>
          <span className="gate-word">bursar</span>
          <span className="gate-capability">capacity gate</span>
        </div>
        <nav className="gate-nav" aria-label="Capabilities">
          <a className="gate-nav-link active" href="#capacity">
            capacity
          </a>
          <a className="gate-nav-link" href="#precondition">
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
          <span className="gate-chain">two capabilities</span>
        </div>
      </header>

      <main className="gate-wrap">
        <section className="gate-hero">
          <div>
            <div className="eyebrow">
              <span className="line" />
              The gate is the product
            </div>
            <h1>
              Ask. <em>Watch the gate.</em>
            </h1>
            <p className="gate-lede">
              A sentence becomes a real payment proposal. Rigorix is the only path to the money: at
              the moment of sending it checks the cap and the payee, then executes or stops the
              payment. Every attempt, allowed or refused, is recorded.
            </p>
          </div>
          <div className="gate-hero-capacity">
            <div className="gate-hero-label">
              <span>Free capacity</span>
              <span>live</span>
            </div>
            <div className="gate-hero-number">{money(capacity?.headroom)}</div>
            <div className="gate-hero-sub">
              <span>of {money(capacity?.cap)}</span>
              <span>committed {money(capacity?.committed)}</span>
              <span>reserved {money(capacity?.reserved)}</span>
            </div>
            {capacity ? <CapacityBar capacity={capacity} /> : <div className="gate-bar" />}
          </div>
        </section>

        <div className="gate-grid">
          <section className="gate-chat">
            <div className="gate-thread" ref={thread} aria-live="polite">
              {messages.length === 0 ? (
                <div className="gate-empty">
                  <p className="gate-empty-title">Tell the agent what to pay.</p>
                  <p className="gate-empty-copy">
                    It records a real bill, then Rigorix decides at the moment of sending. With €30
                    free, €20 goes through and the next €11 is stopped by the gate. Both attempts are
                    signed. Try both.
                  </p>
                  <div className="gate-chips">
                    {examples.map((example) => (
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
                      <GateCard trace={message.trace} />
                    ) : (
                      <p className="gate-text">{message.text}</p>
                    )}
                  </div>
                ),
              )}

              {busy ? (
                <div className="gate-msg agent">
                  <span className="gate-who">agent</span>
                  <p className="gate-thinking">proposing · checking capacity · running the gate…</p>
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
            <p className="gate-world-sub">Set the capacity. Reset the day. Then ask again.</p>

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
                <button className="gate-apply" onClick={() => void applyWorld()} disabled={busy}>
                  apply &amp; reset
                </button>
              </div>
            </label>

            <div className="gate-world-stats">
              <div>
                <span>committed</span>
                <b>{money(capacity?.committed)}</b>
              </div>
              <div>
                <span>reserved</span>
                <b>{money(capacity?.reserved)}</b>
              </div>
              <div>
                <span>free</span>
                <b>{money(capacity?.headroom)}</b>
              </div>
            </div>

            <div className="gate-payees">
              <div className="gate-payees-head">payees</div>
              {state?.payees.map((payee) => (
                <div key={payee.id} className="gate-payee-row">
                  <span>{payee.name}</span>
                  <span className={`gate-payee-status ${payee.status}`}>
                    {payee.status === "eligible" ? "active" : payee.status}
                  </span>
                </div>
              ))}
            </div>

            <div className="gate-note">
              Rigorix decides at the moment of sending. If the payment fits, it executes; if not, it
              stops before anything is broadcast. Either way, the decision is signed.
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
