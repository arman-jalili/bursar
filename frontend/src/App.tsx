import { useCallback, useEffect, useMemo, useState } from "react";
import {
  approveConsole,
  demoState,
  loadState,
  signApproval,
  verifyEvidence,
  type BursarState,
} from "./api";
import {
  INITIAL_APPROVAL,
  SPLIT,
  WIEN,
  ZAHNARZT,
  formatAmount,
  leftToday,
  sumCommitted,
  type ApprovalRequest,
  type Attempt,
  type VerifyState,
} from "./data";
import { Attention } from "./components/Attention";
import { Constitution, type ActiveRule } from "./components/Constitution";
import { EvidenceDrawer } from "./components/EvidenceDrawer";
import { Feed, type FeedFilter } from "./components/Feed";
import { Lab } from "./components/Lab";
import { STORY, StoryRail } from "./components/StoryRail";
import { TopBar } from "./components/TopBar";

function newId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}`;
}

function approvalFor(attempt: Attempt): ApprovalRequest {
  return {
    ...INITIAL_APPROVAL,
    approvalId: attempt.approvalId,
    attemptId: attempt.id,
    invoiceId: attempt.invoiceId,
    payee: attempt.payee,
    amountUsdc: attempt.amountUsdc,
    eip712: {
      ...INITIAL_APPROVAL.eip712,
      message: {
        ...INITIAL_APPROVAL.eip712.message,
        payee: attempt.payee.address,
        amount: attempt.amountUsdc,
        invoiceId: `0x${attempt.invoiceId.replace(/\W/g, "").padEnd(64, "0").slice(0, 64)}`,
      },
    },
  };
}

function storyBase(current: BursarState): BursarState {
  return {
    ...current,
    attempts: current.attempts.filter((a) => a.status === "settled"),
    approval: null,
  };
}

function applyScenario(s: BursarState, id: string): BursarState {
  const now = new Date().toISOString();
  if (id === "normal") {
    const attempt: Attempt = {
      id: newId("att-normal"),
      invoiceId: "INV-2026-0318",
      payee: WIEN,
      amountUsdc: "28400000",
      status: "settled",
      createdAt: now,
      decision: {
        allow: true,
        source: "rigorix-dispatch",
        rule: "standing-record",
        reason: "Known payee, amount inside the caps.",
      },
      settlement: {
        txHash: `0x${"c".repeat(64)}`,
        block: s.chain.block + 1,
        receipt: "0xc18a…22f0",
      },
      narrative: "A new water bill. The payee and amount are inside your rules. Paid.",
    };
    return {
      ...s,
      attempts: [attempt, ...s.attempts],
      chain: { ...s.chain, block: s.chain.block + 1, sealed: s.chain.sealed + 1 },
    };
  }

  if (id === "poisoned") {
    const attempt: Attempt = {
      id: newId("att-poisoned"),
      invoiceId: "INV-2026-0999",
      payee: WIEN,
      amountUsdc: "1190000000",
      status: "refused",
      createdAt: now,
      decision: {
        allow: false,
        source: "rigorix-dispatch",
        rule: "bank_digest_mismatch",
        reason:
          "The presented bank digest differs from the verified one. The payee is quarantined and no transaction was sent.",
      },
      rigorix: {
        executionId: newId("exec"),
        envelopeHash: `0x${"d".repeat(64)}`,
        envelopeUri: "/api/attempts/new/envelope",
      },
      narrative:
        "The invoice says the bank details changed. The verified digest does not match. No transaction was sent.",
    };
    return { ...s, attempts: [attempt, ...s.attempts] };
  }

  if (id === "split") {
    const committed = sumCommitted(s.attempts);
    const wouldBe = committed + 4 * 90_000_000 + 90_000_000;
    const wouldLabel = formatAmount(String(wouldBe));
    const capLabel = formatAmount(s.policy.dailyCapUsdc);
    const attempt: Attempt = {
      id: newId("att-split"),
      invoiceId: "INV-2026-0413",
      payee: SPLIT,
      amountUsdc: "90000000",
      status: "refused",
      createdAt: now,
      decision: {
        allow: false,
        source: "authority",
        rule: "daily_cap",
        reason: `The fifth of six split invoices would make ${wouldLabel} today; the daily cap is ${capLabel}.`,
      },
      rigorix: {
        executionId: newId("exec"),
        envelopeHash: `0x${"e".repeat(64)}`,
        envelopeUri: "/api/attempts/new/envelope",
      },
      narrative: `The fifth of six split invoices from different suppliers. Paying it would make ${wouldLabel} today. Your daily cap is ${capLabel}.`,
    };
    return { ...s, attempts: [attempt, ...s.attempts] };
  }

  if (id === "new-payee") {
    const attempt: Attempt = {
      id: newId("att-new-payee"),
      invoiceId: "INV-2026-0311",
      payee: ZAHNARZT,
      amountUsdc: "240000000",
      status: "pending_approval",
      createdAt: now,
      decision: {
        allow: false,
        source: "rigorix-plan",
        rule: "new_payee",
        reason: "The payee is new and the amount is above the €100 approval line.",
      },
      narrative: "A new payee, above your €100 line. I have not paid it.",
    };
    return {
      ...s,
      attempts: [attempt, ...s.attempts],
      approval: approvalFor(attempt),
    };
  }

  if (id === "freeze") {
    const frozenIds = [...new Set([...s.policy.frozenPayeeIds, ZAHNARZT.id])];
    const pending = s.attempts.find(
      (a) =>
        a.payee.id === ZAHNARZT.id &&
        (a.status === "pending_approval" || a.status === "allowed"),
    );
    if (pending) {
      return {
        ...s,
        policy: { ...s.policy, frozenPayeeIds: frozenIds },
        approval: null,
        attempts: s.attempts.map((a) =>
          a.id === pending.id
            ? {
                ...a,
                status: "refused",
                decision: {
                  allow: false,
                  source: "rigorix-dispatch",
                  rule: "payee_frozen",
                  reason:
                    "The payee was frozen after approval. Dispatch re-read the live state.",
                },
                narrative:
                  "You froze this payee after approving. At dispatch, Rigorix re-read the live state and refused.",
              }
            : a,
        ),
      };
    }
    const frozen: Attempt = {
      id: newId("att-frozen"),
      invoiceId: "INV-2026-0311",
      payee: ZAHNARZT,
      amountUsdc: "240000000",
      status: "refused",
      createdAt: now,
      decision: {
        allow: false,
        source: "rigorix-dispatch",
        rule: "payee_frozen",
        reason: "The payee was frozen after approval. Dispatch re-read the live state.",
      },
      narrative:
        "You froze this payee after approving. At dispatch, Rigorix re-read the live state and refused.",
    };
    return {
      ...s,
      policy: { ...s.policy, frozenPayeeIds: frozenIds },
      attempts: [frozen, ...s.attempts],
      approval: null,
    };
  }

  return s;
}

export default function App() {
  const [state, setState] = useState<BursarState>(() => demoState());
  const [filter, setFilter] = useState<FeedFilter>("all");
  const [query, setQuery] = useState("");
  const [signed, setSigned] = useState(false);
  const [signing, setSigning] = useState(false);
  const [verified, setVerified] = useState<Record<string, VerifyState>>({});
  const [drawerAttempt, setDrawerAttempt] = useState<Attempt | null>(null);
  const [storyStep, setStoryStep] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [live, setLive] = useState(false);

  const showToast = useCallback((message: string) => setToast(message), []);

  useEffect(() => {
    let alive = true;
    loadState().then((next) => {
      if (!alive) return;
      setState(next);
      setLive(next.source === "api");
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 4600);
    return () => window.clearTimeout(id);
  }, [toast]);

  const pending = state.attempts.find((a) => a.status === "pending_approval") ?? null;
  const approval: ApprovalRequest | null = signed
    ? state.approval ?? null
    : pending
      ? state.approval?.attemptId === pending.id
        ? state.approval
        : approvalFor(pending)
      : null;

  const counts = useMemo<Record<FeedFilter, number>>(
    () => ({
      all: state.attempts.length,
      needs: state.attempts.filter((a) => a.status === "pending_approval").length,
      refused: state.attempts.filter((a) => a.status === "refused").length,
      paid: state.attempts.filter((a) => a.status === "settled").length,
    }),
    [state.attempts],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return [...state.attempts]
      .filter((a) => {
        if (filter === "needs" && a.status !== "pending_approval") return false;
        if (filter === "refused" && a.status !== "refused") return false;
        if (filter === "paid" && a.status !== "settled") return false;
        if (
          q &&
          !a.payee.name.toLowerCase().includes(q) &&
          !a.invoiceId.toLowerCase().includes(q) &&
          !a.narrative.toLowerCase().includes(q)
        )
          return false;
        return true;
      })
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  }, [state.attempts, filter, query]);

  const activeRule: ActiveRule = useMemo(() => {
    const pendingNew = state.attempts.find(
      (a) => a.status === "pending_approval" && a.payee.new,
    );
    if (pendingNew) return "new-payee";
    const refusals = state.attempts
      .filter((a) => a.status === "refused")
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
    const rule = refusals[0]?.decision?.rule;
    if (rule === "bank_digest_mismatch") return "bank-change";
    if (rule === "daily_cap") return "daily-cap";
    if (rule === "payee_frozen") return "freeze";
    if (state.policy.frozenPayeeIds.length > 0) return "freeze";
    return null;
  }, [state.attempts, state.policy.frozenPayeeIds]);

  const ruleEvidence = useMemo(() => {
    const wanted =
      activeRule === "bank-change"
        ? "bank_digest_mismatch"
        : activeRule === "daily-cap"
          ? "daily_cap"
          : activeRule === "freeze"
            ? "payee_frozen"
            : null;
    return wanted ? state.attempts.find((a) => a.status === "refused" && a.decision?.rule === wanted) : undefined;
  }, [state.attempts, activeRule]);

  const hasWallet =
    typeof window !== "undefined" && Boolean((window as { ethereum?: unknown }).ethereum);

  const committed = sumCommitted(state.attempts);
  const left = leftToday(state.policy, state.attempts);
  const cap = Number(state.policy.dailyCapUsdc);
  const pct = cap > 0 ? Math.min(100, (left / cap) * 100) : 0;

  const onSign = useCallback(async () => {
    const request = state.approval;
    if (!request || signed || signing) return;
    setSigning(true);
    try {
      if (request.approvalId && state.source === "api") {
        const { signature } = await signApproval(request);
        const outcome = await approveConsole(request.approvalId, signature);
        if (!outcome.granted) {
          throw new Error(outcome.reason_plain ?? "authority refused the signature");
        }
      } else {
        await new Promise((resolve) => window.setTimeout(resolve, 700));
      }
      setSigned(true);
      setFilter("all");
      setState((s) => ({
        ...s,
        attempts: s.attempts.map((a) =>
          a.id === request.attemptId
            ? {
                ...a,
                status: "settled",
                decision: {
                  allow: true,
                  source: "rigorix-dispatch",
                  rule: "owner_signature",
                  reason: "Owner EIP-712 signature verified at dispatch and on-chain.",
                },
                settlement: {
                  txHash: `0x${"a".repeat(64)}`,
                  block: s.chain.block + 1,
                  receipt: "0x7c3d…91aa",
                },
                narrative:
                  "The owner signed the exact payment. Rigorix dispatched it and USDC settled.",
                rigorix: {
                  ...a.rigorix,
                  executionId: a.rigorix?.executionId ?? "01a1d567-9fd7-7ee2-8fa8-22c7af0a07af",
                  envelopeHash: `0x${"b".repeat(64)}`,
                  envelopeUri: `/api/attempts/${a.id}/envelope`,
                  anchoredTx: s.chain.anchor,
                },
              }
            : a,
        ),
        chain: { ...s.chain, block: s.chain.block + 1, sealed: s.chain.sealed + 1 },
      }));
      showToast("Signed. Dispatch authorised — the receipt is ready to verify.");
    } catch (err) {
      showToast(`Approval failed: ${(err as Error).message}`);
    } finally {
      setSigning(false);
    }
  }, [state.approval, state.source, signed, signing, showToast]);

  const onDeny = useCallback(async () => {
    const request = state.approval;
    if (!request) return;
    // The console surface has no deny write: the refusal is recorded locally and
    // no dispatch happens. Authority still holds the intent until it expires.
    setState((s) => ({
      ...s,
      approval: null,
      attempts: s.attempts.map((a) =>
        a.id === request.attemptId
          ? {
              ...a,
              status: "refused",
              decision: {
                allow: false,
                source: "authority",
                rule: "owner_declined",
                reason: "The owner declined the payment.",
              },
            }
          : a,
      ),
    }));
    setSigned(false);
    showToast("Declined. No dispatch, no transaction.");
  }, [state.approval, showToast]);

  const onReview = useCallback(
    (attempt: Attempt) => {
      setSigned(false);
      setState((s) => ({ ...s, approval: approvalFor(attempt) }));
      window.scrollTo({ top: 0, behavior: "smooth" });
      showToast("Approval ready. Sign the exact payment at the top of the page.");
    },
    [showToast],
  );

  const onVerify = useCallback(
    async (attempt: Attempt) => {
      if (attempt.evidenceId && state.source === "api") {
        try {
          const result = await verifyEvidence(attempt.evidenceId);
          const ok = result.outcome === "verified";
          setVerified((v) => ({ ...v, [attempt.id]: ok ? "ok" : "bad" }));
          showToast(
            ok
              ? `Evidence verified — ${result.envelope_id} is intact.`
              : `Evidence verdict: ${result.outcome}. The envelope is not intact.`,
          );
        } catch (err) {
          setVerified((v) => ({ ...v, [attempt.id]: "bad" }));
          showToast(`Evidence check failed: ${(err as Error).message}`);
        }
        return;
      }
      setVerified((v) => ({ ...v, [attempt.id]: "ok" }));
      showToast("Verified — demo envelope. Flip a byte to see it fail.");
    },
    [state.source, showToast],
  );

  const onFlip = useCallback(
    (attempt: Attempt) => {
      setVerified((v) => ({ ...v, [attempt.id]: "bad" }));
      showToast("One byte changed — the signature no longer verifies. That is the point.");
    },
    [showToast],
  );

  const startStory = useCallback(async () => {
    // The story is a local overlay on today's world: it never resets the console,
    // so a live approval or receipt survives a run.
    setState(applyScenario(storyBase(state), "normal"));
    setStoryStep(0);
    setSigned(false);
    setSigning(false);
    setVerified({});
    setDrawerAttempt(null);
    setFilter("all");
    setQuery("");
    window.scrollTo({ top: 0, behavior: "smooth" });
    showToast("Story started. Scene 1 — a normal bill pays and settles.");
  }, [state, showToast]);

  const nextStory = useCallback(async () => {
    if (storyStep === null) return;
    const next = storyStep + 1;
    if (next >= STORY.length) {
      setStoryStep(null);
      showToast("Story complete — all five scenes ran. The receipts remain.");
      return;
    }
    const scene = STORY[next];
    setState(applyScenario(state, scene.id));
    setStoryStep(next);
    if (scene.id === "new-payee") {
      setSigned(false);
      setFilter("needs");
      window.scrollTo({ top: 0, behavior: "smooth" });
      showToast("Scene 4 — sign the exact payment at the top, then continue.");
    } else if (scene.id === "freeze") {
      setSigned(false);
      setFilter("all");
      showToast("Scene 5 — the payee is frozen. The next dispatch refuses.");
    } else {
      showToast(`Scene ${next + 1} — ${scene.label}.`);
    }
  }, [storyStep, state, showToast]);

  const exitStory = useCallback(() => {
    setStoryStep(null);
    showToast("Story mode off. The ledger stays as it is.");
  }, [showToast]);

  const onStoryButton = useCallback(() => {
    if (storyStep === null) {
      startStory();
    } else {
      document.querySelector(".story")?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [storyStep, startStory]);

  return (
    <div className="app">
      <TopBar
        mode={state.mode}
        block={state.chain.block}
        source={state.source}
        live={live}
        query={query}
        storyActive={storyStep !== null}
        onQuery={setQuery}
        onStory={onStoryButton}
      />

      <section className="masthead">
        <div>
          <div className="eyebrow">
            <span className="line" />
            The Weiss household · Saturday, 14 November
          </div>
          <h1>
            Bills paid.
            <br />
            <em>Rules kept.</em>
          </h1>
          <p className="masthead-sub">
            An agent pays the bills. You write the rules. Rigorix enforces them at the moment of
            payment — and every decision leaves a signed receipt.
          </p>
        </div>
        <div className="daily-chip">
          <div className="k">
            <span>Left to spend today</span>
            <span>live</span>
          </div>
          <div className="v">
            {formatAmount(String(left))} <small>of {formatAmount(state.policy.dailyCapUsdc)}</small>
          </div>
          <div className="s">{formatAmount(String(committed))} committed · resets at midnight</div>
          <div className="bar">
            <i style={{ width: `${pct}%` }} />
          </div>
        </div>
      </section>

      <div className="narration">
        <span className="who">agent</span>
        <span>
          I propose the payment. <b>Rigorix</b> checks the rules. <b>You</b> sign the exceptions.
          Every decision leaves a receipt.
        </span>
      </div>

      <Attention
        request={approval}
        policy={state.policy}
        chain={state.chain}
        attempts={state.attempts}
        signed={signed}
        signing={signing}
        hasWallet={hasWallet}
        storyActive={storyStep !== null}
        onSign={onSign}
        onDeny={onDeny}
        onStartStory={startStory}
        onOpenEvidence={(attempt) => setDrawerAttempt(attempt)}
      />

      <StoryRail
        active={storyStep !== null}
        step={storyStep}
        onStart={startStory}
        onNext={nextStory}
        onExit={exitStory}
        onRestart={startStory}
      />

      <Lab />

      <div className="feed-layout">
        <Feed
          attempts={filtered}
          filter={filter}
          counts={counts}
          onFilter={setFilter}
          onOpenEvidence={(attempt) => setDrawerAttempt(attempt)}
          onReview={onReview}
        />
        <div className="rules-panel">
          <Constitution
            policy={state.policy}
            attempts={state.attempts}
            activeRule={activeRule}
            onToggleQuarantine={() => {
              setState((s) => ({
                ...s,
                policy: { ...s.policy, quarantineOnBankChange: !s.policy.quarantineOnBankChange },
              }));
              showToast(
                state.policy.quarantineOnBankChange
                  ? "Quarantine off. Only the owner can change this; the next run uses the new rule."
                  : "Quarantine on. A changed bank detail is refused at dispatch.",
              );
            }}
            onViewEvidence={
              ruleEvidence ? () => setDrawerAttempt(ruleEvidence) : undefined
            }
          />
        </div>
      </div>

      <EvidenceDrawer
        attempt={drawerAttempt}
        source={state.source}
        verified={drawerAttempt ? verified[drawerAttempt.id] : undefined}
        onClose={() => setDrawerAttempt(null)}
        onVerify={onVerify}
        onFlip={onFlip}
      />

      {toast ? <div className="toast">{toast}</div> : null}
    </div>
  );
}
