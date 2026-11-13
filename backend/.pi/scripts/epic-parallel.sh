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

# The project dir (owner of .pi/) is NOT necessarily the git top level: a
# monorepo keeps the app in <repo>/backend with .pi/ inside it.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FREEZE_SH="$PROJECT_DIR/.pi/scripts/freeze.sh"
if [ -f "$FREEZE_SH" ]; then
	if ! bash "$FREEZE_SH" verify --module "$MODULE" >/dev/null 2>&1; then
		echo "⛔ Blocked: '$MODULE' is not frozen (freeze.sh verify failed)."
		echo ""
		echo "   Freeze it first:"
		echo "     /architect --freeze --module \"$MODULE\""
		echo "   then merge the contract-freeze PR and record it:"
		echo "     bash .pi/scripts/freeze.sh record --module \"$MODULE\" --commit <sha>"
		echo ""
		echo "   Detail:"
		bash "$FREEZE_SH" verify --module "$MODULE" 2>&1 | sed 's/^/     /'
		exit 2
	fi
else
	echo "⛔ missing .pi/scripts/freeze.sh — run guardian update" >&2
	exit 1
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
# Register in the shared registry. The script lives in the PROJECT dir (which
# owns .pi/), not necessarily at the git top level — looking at $ROOT skipped
# registration silently in a monorepo, leaving list with branch=? worktree=?.
EPIC_REG="$PROJECT_DIR/.pi/scripts/epic-registry.sh"
if [ -x "$EPIC_REG" ]; then
	bash "$EPIC_REG" register "$MODULE" --branch "$BRANCH" --worktree "$DIR" --status running
else
	echo "  (warning: epic-registry.sh not found at $EPIC_REG — branch/worktree not recorded)" >&2
fi

echo ""
echo "✅ Worktree ready."
echo "   Next: cd \"$DIR\" && /architect --epic \"$MODULE\""
echo "   The epic runs in epic mode: one branch, local CI per issue, one PR at the end."
