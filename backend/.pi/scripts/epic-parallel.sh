#!/usr/bin/env bash
# ============================================================================
# epic-parallel.sh — start an epic in its own git worktree (parallel epics)
# ============================================================================
# Parallel epics work when (a) each module is isolated in its own worktree,
# (b) there is one epic branch per module, and (c) the module's shared
# contracts are FROZEN (merged) so the parallel work cannot redefine them.
#
# Run as: bash .pi/scripts/epic-parallel.sh <module> [--base main] [--dir <path>]
# Exit:  0 worktree ready · 2 blocked by contract freeze · 1 error
# ============================================================================
set -uo pipefail

MODULE="${1:-}"
shift || true
BASE="main"; DIR=""
while [ $# -gt 0 ]; do
	case "$1" in
		--base) BASE="${2:-main}"; shift 2 ;;
		--dir) DIR="${2:-}"; shift 2 ;;
		*) shift ;;
	esac
done

if [ -z "$MODULE" ]; then
	echo "usage: epic-parallel.sh <module> [--base main] [--dir <path>]" >&2
	exit 1
fi

slug() { echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'; }
BRANCH="epic/$(slug "$MODULE")"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "not a git repo" >&2; exit 1; }
REG="$(git rev-parse --git-common-dir 2>/dev/null || echo "$ROOT/.git")"
[ -d "$REG" ] || REG="$ROOT/.git"
REPO_NAME="$(basename "$ROOT")"
[ -z "$DIR" ] && DIR="$(dirname "$ROOT")/${REPO_NAME}-$(slug "$MODULE")"

echo "============================================"
echo "  Parallel epic: $MODULE"
echo "============================================"
echo "  branch:   $BRANCH"
echo "  worktree: $DIR"
echo ""

# ── Contract-freeze gate ────────────────────────────────────────────────────
# An epic may only run in parallel once its shared contracts are frozen. The
# registry is the source of truth (set by the contract-freeze issue / a human).
REG_FILE="$REG/guardian/epics.json"
FROZEN="unknown"
if [ -f "$REG_FILE" ]; then
	FROZEN=$(python3 - "$REG_FILE" "$MODULE" <<'PY' 2>/dev/null || echo unknown
import json,sys
d=json.load(open(sys.argv[1]))
e=d.get("epics",{}).get(sys.argv[2],{})
print("true" if e.get("contractFrozen") else ("false" if e else "unknown"))
PY
)
fi

if [ "$FROZEN" != "true" ]; then
	# NOTE: block here (before worktree creation) and exit 2 — a non-zero,
	# distinguishable code so callers/agents cannot mistake it for success.
	echo "⛔ Blocked: contracts for '$MODULE' are not frozen (registry: $FROZEN)."
	echo ""
	echo "   Parallel epics must not redefine shared contracts. Freeze first:"
	echo "     1. run the epic's Contract Freeze issue and merge it to $BASE"
	echo "     2. record it:  bash .pi/scripts/epic-registry.sh freeze \"$MODULE\" --frozen"
	echo ""
	echo "   (single-epic work does not need this gate)"
	exit 2
fi

# ── Worktree creation ───────────────────────────────────────────────────────
if [ -e "$DIR" ]; then
	echo "worktree path already exists: $DIR"
elif git show-ref --verify --quiet "refs/heads/$BRANCH"; then
	echo "branch exists — attaching worktree"
	git worktree add "$DIR" "$BRANCH" || exit 1
else
	echo "creating branch + worktree from origin/$BASE"
	git fetch origin "$BASE" --quiet 2>/dev/null || true
	git worktree add -b "$BRANCH" "$DIR" "origin/$BASE" 2>/dev/null || \
		git worktree add -b "$BRANCH" "$DIR" "$BASE" || exit 1
fi

# ── Register in the shared registry ─────────────────────────────────────────
if [ -x "$ROOT/.pi/scripts/epic-registry.sh" ]; then
	bash "$ROOT/.pi/scripts/epic-registry.sh" register "$MODULE" --branch "$BRANCH" --worktree "$DIR" --status running
fi

echo ""
echo "✅ Worktree ready."
echo "   Next: cd \"$DIR\" && /architect --epic \"$MODULE\""
echo "   The epic runs in epic mode: one branch, local CI per issue, one PR at the end."
