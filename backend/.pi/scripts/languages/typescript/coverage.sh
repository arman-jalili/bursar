#!/usr/bin/env bash
# ============================================================================
# coverage.sh — TypeScript/JavaScript: real line coverage via the project's
# coverage-enabled test runner
#
# Runs the test suite with coverage enabled, using the first runner that is
# actually installed: vitest → jest → bun test --coverage → c8. All of them
# emit a text table with an "All files" summary row; the "% Lines" column is
# parsed from it (header-driven — istanbul-style tables have 5 percentage
# columns, bun's has 2). No heuristic grep counting.
#
# Usage (normally via the .pi/scripts/coverage.sh dispatcher):
#   bash coverage.sh            # measure coverage
#   bash coverage.sh --gate     # fail if lines < COVERAGE_THRESHOLD
#   bash coverage.sh --lcov     # report an existing lcov artifact, if any
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

# Walk up from CWD to the project root (package.json).
ROOT="$(pwd)"
while [ "$ROOT" != "/" ] && [ ! -f "$ROOT/package.json" ]; do
    ROOT="$(dirname "$ROOT")"
done
if [ ! -f "$ROOT/package.json" ]; then
    echo "✗ No package.json found in this directory tree" >&2
    exit 1
fi
cd "$ROOT" || exit 1

OUT_FILE="$(mktemp)"
trap 'rm -f "$OUT_FILE"' EXIT

run_and_capture() {
    # shellcheck disable=SC2015
    "$@" >"$OUT_FILE" 2>&1 || true
}

echo "═══ Coverage (real test-runner coverage) ═══"
RUN=""
if [ -x "node_modules/.bin/vitest" ]; then
    echo "  runner: vitest"
    run_and_capture node_modules/.bin/vitest run --coverage
    RUN="vitest"
elif command -v vitest >/dev/null 2>&1; then
    echo "  runner: vitest (PATH)"
    run_and_capture vitest run --coverage
    RUN="vitest"
elif [ -x "node_modules/.bin/jest" ]; then
    echo "  runner: jest"
    run_and_capture node_modules/.bin/jest --coverage
    RUN="jest"
elif command -v jest >/dev/null 2>&1; then
    echo "  runner: jest (PATH)"
    run_and_capture jest --coverage
    RUN="jest"
elif command -v bun >/dev/null 2>&1; then
    echo "  runner: bun test --coverage"
    run_and_capture bun test --coverage
    RUN="bun"
elif [ -x "node_modules/.bin/c8" ]; then
    # c8 (istanbul) wraps the project's own test command.
    echo "  runner: c8 (npm test)"
    run_and_capture node_modules/.bin/c8 --reporter=text npm test
    RUN="c8"
else
    echo "✗ No coverage-enabled test runner found (vitest/jest/bun/c8)" >&2
    echo "  run .pi/scripts/install_coverage_tools.sh for guidance" >&2
    exit 1
fi

# Parse the "% Lines" column of the "All files" row from the runner's text
# table. Header-driven: locate the "% Lines" column in the header row, then
# read it from the "All files" summary row (istanbul-style tables list
# % Stmts, % Branch, % Funcs, % Lines; bun lists % Funcs, % Lines).
COVERAGE="$(python3 - "$OUT_FILE" <<'PY'
import sys, re
with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    lines = [ln.strip() for ln in fh]

header = next((ln for ln in lines if ln.startswith("File") and "%" in ln), None)
allrow = next((ln for ln in lines if ln.startswith("All files")), None)
if not header or not allrow:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)%", lines[-1] if lines else "")
    print(m.group(1) if m else "")
    raise SystemExit

cols = [c.strip() for c in header.split("|")]
idx = next(
    (i for i, c in enumerate(cols) if c.replace("%", "").strip().lower() == "lines"),
    None,
)
if idx is None:
    idx = next((i for i, c in enumerate(cols) if c.startswith("%")), 1) + 1

cells = [c.strip() for c in allrow.split("|")]
if idx is not None and idx < len(cells):
    val = cells[idx].replace("%", "").strip()
    if val.replace(".", "", 1).isdigit():
        print(val)
        raise SystemExit
m = re.search(r"([0-9]+(?:\.[0-9]+)?)%", allrow)
print(m.group(1) if m else "")
PY
)"

tail -8 "$OUT_FILE"
echo ""
echo "Line coverage: ${COVERAGE:-unavailable}% (threshold: ${COVERAGE_THRESHOLD}%, runner: ${RUN})"

if [ -z "$COVERAGE" ]; then
    echo "✗ Could not extract an 'All files' line-coverage percentage from ${RUN} output." >&2
    echo "  Ensure the runner is configured to emit a text coverage summary" >&2
    echo "  (vitest: coverage.reporter includes 'text'; jest: coverageReporters includes 'text')." >&2
    exit 1
fi

if [ "$LCOV" -eq 1 ]; then
    LCOV_FOUND=""
    for cand in "coverage/lcov.info" "lcov.info"; do
        if [ -f "$cand" ]; then
            echo "lcov artifact found: $cand"
            LCOV_FOUND=1
            break
        fi
    done
    if [ -z "$LCOV_FOUND" ]; then
        echo "⚠️  no lcov.info artifact found — configure your runner's lcov reporter" >&2
    fi
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
