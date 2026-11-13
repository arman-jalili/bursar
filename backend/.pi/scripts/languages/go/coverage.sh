#!/usr/bin/env bash
# ============================================================================
# coverage.sh — Go: real line coverage via `go test -coverprofile`
#
# Runs the full test suite with a coverage profile and reports total line
# coverage from `go tool cover -func`.
#
# Usage (normally via the .pi/scripts/coverage.sh dispatcher):
#   bash coverage.sh            # measure coverage
#   bash coverage.sh --gate     # fail if lines < COVERAGE_THRESHOLD
#   bash coverage.sh --lcov     # keep coverage.out profile artifact
#
# Env:
#   COVERAGE_THRESHOLD  minimum line-coverage % (default: 60)
# ============================================================================
set -uo pipefail

COVERAGE_THRESHOLD="${COVERAGE_THRESHOLD:-60}"
GATE=0
LCOV=0

for arg in "$@"; do
    case "$arg" in
        --gate) GATE=1 ;;
        --lcov) LCOV=1 ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# Walk up from CWD to the module root (go.mod).
ROOT="$(pwd)"
while [ "$ROOT" != "/" ] && [ ! -f "$ROOT/go.mod" ]; do
    ROOT="$(dirname "$ROOT")"
done
if [ ! -f "$ROOT/go.mod" ]; then
    echo "✗ No go.mod found in this directory tree" >&2
    exit 1
fi
cd "$ROOT" || exit 1

if ! command -v go >/dev/null 2>&1; then
    echo "✗ go toolchain not found on PATH" >&2
    exit 1
fi

echo "═══ Coverage (go test -coverprofile) ═══"
go test -coverprofile=coverage.out ./... 2>&1 | tail -10

if [ ! -f "coverage.out" ]; then
    echo "✗ No coverage profile generated (go test -coverprofile failed)" >&2
    exit 1
fi

FUNC_OUT="$(go tool cover -func=coverage.out 2>/dev/null || true)"
COVERAGE="$(echo "$FUNC_OUT" | awk '/^total:/{print $NF}' | tr -d '%')"
echo ""
echo "Line coverage: ${COVERAGE:-unavailable}% (threshold: ${COVERAGE_THRESHOLD}%)"

if [ -z "$COVERAGE" ]; then
    echo "✗ Could not extract total coverage from coverage profile" >&2
    exit 1
fi

if [ "$LCOV" -eq 1 ]; then
    echo "coverage profile artifact kept: coverage.out"
else
    rm -f coverage.out
fi

if [ "$GATE" -eq 1 ]; then
    if awk "BEGIN { exit !($COVERAGE >= $COVERAGE_THRESHOLD) }"; then
        echo "✓ Coverage gate passed"
    else
        echo "✗ Coverage below threshold (${COVERAGE}% < ${COVERAGE_THRESHOLD}%)" >&2
        exit 1
    fi
fi
exit 0
