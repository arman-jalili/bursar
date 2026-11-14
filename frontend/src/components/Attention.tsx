import type { ApprovalRequest, Attempt, ChainState, Policy } from "../data";
import { formatAmount, shortHash, timeLabel } from "../data";

interface Props {
  request: ApprovalRequest | null;
  policy: Policy;
  chain: ChainState;
  attempts: Attempt[];
  signed: boolean;
  signing: boolean;
  hasWallet: boolean;
  storyActive: boolean;
  onSign: () => void;
  onDeny: () => void;
  onStartStory: () => void;
  onOpenEvidence: (attempt: Attempt) => void;
}

export function Attention({
  request,
  policy,
  chain,
  attempts,
  signed,
  signing,
  hasWallet,
  storyActive,
  onSign,
  onDeny,
  onStartStory,
  onOpenEvidence,
}: Props) {
  const lastRefusal = attempts.find((a) => a.status === "refused");
  const signedAttempt = request
    ? attempts.find((a) => a.id === request.attemptId && a.status === "settled")
    : undefined;
  const paid = attempts.filter((a) => a.status === "settled").length;
  const refused = attempts.filter((a) => a.status === "refused").length;
  const waiting = attempts.filter((a) => a.status === "pending_approval").length;

  if (request && !signed) {
    return (
      <section className="attention" aria-label="Needs your attention">
        <div className="attention-card">
          <div className="attention-main">
            <span className="attention-eyebrow">● Needs you now · owner signature</span>
            <h2>
              Approve <span className="amt">{formatAmount(request.amountUsdc)}</span> to{" "}
              {request.payee.name}?
            </h2>
            <p className="attention-sub">
              New payee · above your {formatAmount(policy.approvalThresholdUsdc)} line. The agent
              has not paid it. Sign the exact payment to authorise it.
            </p>
            <div className="attention-fields">
              <div className="attention-field">
                <span>invoice</span>
                <b>{request.invoiceId}</b>
              </div>
              <div className="attention-field">
                <span>intent</span>
                <b>{shortHash(request.intentDigest, 8, 4)}</b>
              </div>
              <div className="attention-field">
                <span>payee</span>
                <b>{shortHash(request.payee.address, 8, 4)}</b>
              </div>
              <div className="attention-field">
                <span>nonce · deadline</span>
                <b>
                  {request.nonce} · {timeLabel(request.deadline)}
                </b>
              </div>
            </div>
            <div className="attention-actions">
              <button className="btn pink" onClick={onSign} disabled={signing}>
                {signing ? "Signing…" : "Sign & approve →"}
              </button>
              <button className="btn ghost" onClick={onDeny}>
                Deny
              </button>
              <span className="attention-note">
                {hasWallet ? "EIP-712 via your wallet" : "No wallet detected — demo signer"}
              </span>
            </div>
          </div>

          <aside className="attention-side">
            <div className="k">What happens when you sign</div>
            <div className="what-step">
              <span className="n">1</span>
              <span>
                You sign <b>this exact payment</b> — invoice, payee, amount, nonce.
              </span>
            </div>
            <div className="what-step">
              <span className="n">2</span>
              <span>
                Rigorix <b>re-checks the live state</b> at dispatch.
              </span>
            </div>
            <div className="what-step">
              <span className="n">3</span>
              <span>
                <b>USDC settles</b> through PaymentRouter.
              </span>
            </div>
            <div className="what-step">
              <span className="n">4</span>
              <span>
                The signed receipt <b>verifies in your browser</b>.
              </span>
            </div>
            <span className="funky-note pink" style={{ fontSize: 19, marginTop: 4 }}>
              The agent can&apos;t sign this. Only you can.
            </span>
            <div className="chain">
              {chain.mode === "anvil" ? "Local Anvil" : "Base Sepolia"} · router{" "}
              {shortHash(chain.router, 6, 4)}
            </div>
          </aside>
        </div>
      </section>
    );
  }

  if (request && signed) {
    return (
      <section className="attention" aria-label="Approval complete">
        <div className="attention-card">
          <div className="attention-main">
            <span className="attention-eyebrow" style={{ background: "var(--green-soft)", color: "var(--green)" }}>
              ✓ Signed · dispatch authorised
            </span>
            <h2>Approved. The receipt is ready.</h2>
            <p className="attention-sub">
              {formatAmount(request.amountUsdc)} to {request.payee.name} was authorised with your
              exact intent signature. The evidence is a signed envelope in the ledger.
            </p>
            <div className="attention-signed">
              Signed by the owner · intent {shortHash(request.intentDigest, 8, 4)} · nonce{" "}
              {request.nonce}. No one can change the amount after this point.
            </div>
            <div className="attention-actions">
              {signedAttempt ? (
                <button className="btn pink" onClick={() => onOpenEvidence(signedAttempt)}>
                  Verify the receipt →
                </button>
              ) : null}
              {!storyActive ? (
                <button className="btn ghost" onClick={onStartStory}>
                  Run the story
                </button>
              ) : null}
            </div>
          </div>
          <aside className="attention-side">
            <div className="k">The four steps</div>
            <div className="what-step">
              <span className="n">✓</span>
              <span>
                <b>Signed</b> — exact payment.
              </span>
            </div>
            <div className="what-step">
              <span className="n">✓</span>
              <span>
                <b>Re-checked</b> — live state at dispatch.
              </span>
            </div>
            <div className="what-step">
              <span className="n">✓</span>
              <span>
                <b>Settled</b> — USDC on chain.
              </span>
            </div>
            <div className="what-step">
              <span className="n">✓</span>
              <span>
                <b>Sealed</b> — receipt ready to verify.
              </span>
            </div>
            <div className="chain">
              {chain.mode === "anvil" ? "Local Anvil" : "Base Sepolia"} · block{" "}
              {chain.block.toLocaleString("en-US")}
            </div>
          </aside>
        </div>
      </section>
    );
  }

  return (
    <section className="attention attention-empty" aria-label="Nothing needs you">
      <div className="attention-card">
        <div className="attention-main">
          <span className="attention-eyebrow">Needs you now</span>
          <h2>Nothing needs you right now.</h2>
          <p className="attention-sub">
            The agent is watching the inbox and every payment is inside your rules.{" "}
            {refused > 0
              ? `${refused} payment${refused === 1 ? "" : "s"} were refused — the evidence is below.`
              : "Nothing has been refused today."}
          </p>
          <div className="attention-actions">
            {!storyActive ? (
              <button className="btn pink" onClick={onStartStory}>
                Run the 3-minute story →
              </button>
            ) : null}
            {lastRefusal ? (
              <button className="btn ghost" onClick={() => onOpenEvidence(lastRefusal)}>
                See the last refusal
              </button>
            ) : null}
          </div>
          <div className="attention-note">
            {paid} paid · {refused} refused · {waiting} waiting · resets at midnight
          </div>
        </div>
        <aside className="attention-side">
          <div className="k">Today at a glance</div>
          <div className="what-step">
            <span className="n">✓</span>
            <span>
              <b>{paid} paid</b> — settled in USDC.
            </span>
          </div>
          <div className="what-step">
            <span className="n">✕</span>
            <span>
              <b>{refused} refused</b> — no transaction sent.
            </span>
          </div>
          <div className="what-step">
            <span className="n">◷</span>
            <span>
              <b>{waiting} waiting</b> — for your signature.
            </span>
          </div>
          <div className="chain">
            Rules v3 · owner: Mira W. · {chain.mode === "anvil" ? "Local Anvil" : "Base Sepolia"}
          </div>
        </aside>
      </div>
    </section>
  );
}
