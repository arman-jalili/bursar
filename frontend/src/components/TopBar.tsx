import type { Mode } from "../data";
import type { Source } from "../api";

interface Props {
  mode: Mode;
  block: number;
  source: Source;
  live: boolean;
  query: string;
  storyActive: boolean;
  onQuery: (value: string) => void;
  onStory: () => void;
}

export function TopBar({ mode, block, source, live, query, storyActive, onQuery, onStory }: Props) {
  const chainLabel = mode === "anvil" ? "Local Anvil" : "Base Sepolia";
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark">b</div>
        <div className="brand-word">bursar</div>
      </div>

      <label className="search">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <span className="sr-only">Search bills, payees, receipts</span>
        <input
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Search bills, payees, receipts…"
        />
      </label>

      <div className="top-actions">
        <span className="api-chip" title={source === "api" ? "Connected to console API" : "Demo fixtures"}>
          <span className="dot" />
          {source === "api" ? (live ? "live" : "api") : "demo data"}
        </span>
        <span className="chain-pill">
          <span className="dot" />
          {chainLabel} · block {new Intl.NumberFormat("en-US").format(block)}
        </span>
        <button className="btn pink" onClick={onStory}>
          {storyActive ? "Story running" : "Run story"}
        </button>
        <div className="avatar" title="Mira Weiss · owner">
          MW
        </div>
      </div>
    </header>
  );
}
