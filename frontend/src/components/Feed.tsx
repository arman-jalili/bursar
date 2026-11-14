import type { Attempt } from "../data";
import { formatAmount, timeLabel } from "../data";

export type FeedFilter = "all" | "needs" | "refused" | "paid";

interface Props {
  attempts: Attempt[];
  filter: FeedFilter;
  counts: Record<FeedFilter, number>;
  onFilter: (filter: FeedFilter) => void;
  onOpenEvidence: (attempt: Attempt) => void;
  onReview: (attempt: Attempt) => void;
}

function visualOf(attempt: Attempt): { cls: string; icon: string; label: string } {
  if (attempt.status === "settled") return { cls: "paid", icon: "✓", label: "paid" };
  if (attempt.status === "pending_approval")
    return { cls: "wait", icon: "◷", label: "waiting for you" };
  if (attempt.status === "refused")
    return attempt.decision?.rule === "daily_cap"
      ? { cls: "cap", icon: "◼", label: "refused · cap" }
      : { cls: "refused", icon: "✕", label: "refused" };
  return { cls: "wait", icon: "◷", label: attempt.status };
}

const FILTERS: { id: FeedFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "needs", label: "Needs you" },
  { id: "refused", label: "Refused" },
  { id: "paid", label: "Paid" },
];

export function Feed({ attempts, filter, counts, onFilter, onOpenEvidence, onReview }: Props) {
  return (
    <section aria-label="The agent's day">
      <div className="feed-head">
        <div>
          <h2>The agent&apos;s day</h2>
          <p>Every attempt, including the refusals. Click one to see its receipt.</p>
        </div>
        <span className="status paid">● agent online</span>
      </div>

      <div className="feed-filters">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            className={`chip${filter === f.id ? " active" : ""}`}
            onClick={() => onFilter(f.id)}
          >
            {f.label} <b>{counts[f.id]}</b>
          </button>
        ))}
      </div>

      <div className="feed-list">
        {attempts.length === 0 ? (
          <div className="empty" style={{ marginTop: 14 }}>
            No attempts match this filter. The agent is watching the inbox.
          </div>
        ) : (
          attempts.map((attempt) => {
            const v = visualOf(attempt);
            const pending = attempt.status === "pending_approval";
            return (
              <div
                className="feed-row"
                key={attempt.id}
                onClick={() => (pending ? onReview(attempt) : onOpenEvidence(attempt))}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    pending ? onReview(attempt) : onOpenEvidence(attempt);
                  }
                }}
              >
                <span className={`feed-ic ${v.cls}`} aria-hidden="true">
                  {v.icon}
                </span>
                <div className="feed-main">
                  <div className="feed-top">
                    <span className="feed-name">{attempt.payee.name}</span>
                    <span className="feed-amt">{formatAmount(attempt.amountUsdc)}</span>
                  </div>
                  <p>{attempt.narrative}</p>
                  {attempt.decision?.rule ? (
                    <span className="feed-rule">{attempt.decision.rule}</span>
                  ) : null}
                </div>
                <div className="feed-meta">
                  <span>{timeLabel(attempt.createdAt)}</span>
                  <span className={`status ${v.cls}`}>{v.label}</span>
                  <div className="feed-actions">
                    {pending ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onReview(attempt);
                        }}
                      >
                        Review →
                      </button>
                    ) : attempt.status === "refused" ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenEvidence(attempt);
                        }}
                      >
                        Why?
                      </button>
                    ) : (
                      <button
                        className="muted"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenEvidence(attempt);
                        }}
                      >
                        Receipt
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
