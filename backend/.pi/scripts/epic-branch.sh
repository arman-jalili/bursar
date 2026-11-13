#!/usr/bin/env bash
# ============================================================================
# epic-branch.sh — create or enter the shared epic branch (epic mode)
# ============================================================================
# Epic mode: all issues of an epic commit to ONE branch; a single PR is opened
# after the last issue. This script makes branch handling deterministic for
# agents and humans.
#
# Run as: bash .pi/scripts/epic-branch.sh <module-name> [base-branch]
#         bash .pi/scripts/epic-branch.sh --current
#
# Exit codes: 0 ok, 1 usage/error
# ============================================================================
set -euo pipefail

slugify() {
	echo "$1" | tr '[:upper:]' '[:lower:]' \
		| sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
}

if [ "${1:-}" = "--current" ]; then
	git rev-parse --abbrev-ref HEAD
	exit 0
fi

MODULE="${1:-}"
BASE="${2:-main}"
if [ -z "$MODULE" ]; then
	echo "Usage: epic-branch.sh <module-name> [base-branch] | --current" >&2
	exit 1
fi

BRANCH="epic/$(slugify "$MODULE")"

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
	echo "Epic branch already exists: $BRANCH"
	git checkout "$BRANCH"
else
	echo "Creating epic branch: $BRANCH (from $BASE)"
	git fetch origin "$BASE" --quiet 2>/dev/null || true
	git checkout -b "$BRANCH" "origin/$BASE" 2>/dev/null || git checkout -b "$BRANCH" "$BASE"
fi

echo "On branch: $(git rev-parse --abbrev-ref HEAD)"
echo "Epic mode: commit every issue here; open ONE PR after the last issue:"
echo "  bash .pi/scripts/ci/run_preflight.sh   # local gate per issue"
