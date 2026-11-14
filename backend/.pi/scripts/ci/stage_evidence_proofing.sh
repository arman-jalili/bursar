#!/usr/bin/env bash
# ============================================================================
# stage_evidence_proofing.sh — CI stage: Evidence contract + tests + coverage
#
# Deterministic, no LLM:
#   1. check_evidence_contracts.sh — every frozen interface still has an impl
#   2. the 19 frozen behaviour suites + the integration suites
#   3. real coverage.py gate on src/evidence (the project's coverage tool, not
#      a grep heuristic)
#
# Usage: bash stage_evidence_proofing.sh [--help]
# Exit:  0 pass · 1 any check failed
# ============================================================================
set -uo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT" || exit 1

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTEST="pytest"
[ -x ".venv/bin/pytest" ] && PYTEST=".venv/bin/pytest"

COVERAGE_THRESHOLD="${EVIDENCE_COVERAGE_THRESHOLD:-90}"
FAIL=0

echo "  [1/3] Contract implementation"
if bash "$SCRIPTS_DIR/check_evidence_contracts.sh"; then
    :
else
    FAIL=$((FAIL + 1))
fi

echo "  [2/3] Behaviour + integration suites"
if "$PYTEST" tests/unit/evidence tests/integration/evidence -q; then
    :
else
    FAIL=$((FAIL + 1))
fi

echo "  [3/3] Coverage on src/evidence (≥ ${COVERAGE_THRESHOLD}%)"
if "$PYTEST" tests/unit/evidence tests/integration/evidence \
    --cov=src.evidence --cov-report=term-missing --cov-fail-under="$COVERAGE_THRESHOLD" -q; then
    :
else
    FAIL=$((FAIL + 1))
fi

if [ "$FAIL" -gt 0 ]; then
    echo "  Evidence proofing FAILED (${FAIL} check(s))"
    exit 1
fi
echo "  Evidence proofing passed"
