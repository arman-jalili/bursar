export const STORY = [
  {
    id: "normal",
    label: "Normal bill",
    sub: "pays & settles",
    caption: "A normal bill. The agent pays it, USDC settles, and the signed receipt appears.",
  },
  {
    id: "poisoned",
    label: "Scam invoice",
    sub: "refused at dispatch",
    caption:
      "The invoice says “our bank details changed”. Rigorix refuses at dispatch. No transaction is sent.",
  },
  {
    id: "split",
    label: "Split cap",
    sub: "the fifth is refused",
    caption:
      "Six small invoices. The daily cap refuses the fifth. The agent cannot split around the rule.",
  },
  {
    id: "new-payee",
    label: "New payee",
    sub: "you sign",
    caption:
      "A new payee above €100. The agent escalates; you sign the exact payment. Sign it, then continue.",
  },
  {
    id: "freeze",
    label: "Freeze",
    sub: "dispatch refuses",
    caption:
      "You freeze the payee after approval. At dispatch, Rigorix re-reads the live state and refuses.",
  },
] as const;

interface Props {
  active: boolean;
  step: number | null;
  onStart: () => void;
  onNext: () => void;
  onExit: () => void;
  onRestart: () => void;
}

export function StoryRail({ active, step, onStart, onNext, onExit, onRestart }: Props) {
  const current = step !== null ? STORY[step] : null;
  const last = step !== null && step >= STORY.length - 1;

  return (
    <section className="story" aria-label="Guided demo story">
      <div className="story-card">
        <div className="story-head">
          <div className="story-title">
            The 3-minute story <span>→</span>
          </div>
          <span className="funky-note" style={{ fontSize: 18 }}>
            Five scenes. One invoice at a time.
          </span>
          <button
            className="btn ghost"
            style={{ padding: "7px 12px", fontSize: 12 }}
            onClick={() =>
              document.querySelector(".lab")?.scrollIntoView({ behavior: "smooth", block: "start" })
            }
          >
            Control room ↓
          </button>
        </div>

        <div className="story-steps">
          {STORY.map((s, i) => (
            <div
              key={s.id}
              className={`story-step-card${step === i ? " active" : (step ?? -1) > i ? " done" : ""}`}
            >
              <span className="story-num">{String(i + 1).padStart(2, "0")}</span>
              <span className="story-label">{s.label}</span>
              <span className="story-sub">{s.sub}</span>
            </div>
          ))}
        </div>

        <div className="story-foot">
          <div className="story-caption">
            {active && current ? (
              <>
                <b>Scene {step! + 1}.</b> {current.caption}
              </>
            ) : (
              <>
                Five scenes: a normal bill, a scam, a split, a new payee, a freeze. Watch Rigorix
                enforce the rules at the moment of payment.
              </>
            )}
          </div>

          <div className="story-actions">
            {!active ? (
              <button className="btn pink" onClick={onStart}>
                Start story →
              </button>
            ) : (
              <>
                <button className="btn pink" onClick={onNext}>
                  {last ? "Finish story" : "Next scene →"}
                </button>
                <button className="btn ghost" onClick={onRestart}>
                  Restart
                </button>
                <button className="btn ghost" onClick={onExit}>
                  Exit
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
