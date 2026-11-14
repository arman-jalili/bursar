#!/usr/bin/env bash
# Stage 11: Console Proofing
#
# Verifies the frozen Console contract is still implemented and tested:
# - every frozen behaviour body has a concrete implementation
# - the projections, ACL whitelists, adapters and eight routes exist
# - `src/console/domain/` does not exist (CON-09 / ADR-008)
# - every invariant suite still exists and real coverage holds the floor
#
# The proof itself lives in check_console_contracts.sh (deterministic, zero
# tokens); this wrapper is the CI stage the hardening runner invokes.

set -euo pipefail

FAIL=0
PASS=0

log_pass() { echo "  ✓ PASS: $1"; PASS=$((PASS + 1)); }
log_fail() { echo "  ✗ FAIL: $1 — $2"; FAIL=$((FAIL + 1)); }

echo "  Checking the Console contract is implemented..."

if [[ ! -f ".pi/scripts/ci/check_console_contracts.sh" ]]; then
    log_fail "console contracts" "check_console_contracts.sh is missing"
else
    if bash ".pi/scripts/ci/check_console_contracts.sh"; then
        log_pass "console contracts (implementation, whitelists, routes, no domain layer)"
    else
        log_fail "console contracts" "a frozen contract row is no longer implemented"
    fi
fi

echo ""
echo "  Console proofing: ${PASS} passed, ${FAIL} failed"
if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
exit 0
