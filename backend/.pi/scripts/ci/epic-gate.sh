#!/usr/bin/env bash
# ============================================================================
# epic-gate.sh — local CI gate for one epic issue (no remote PR wait)
# ============================================================================
# In epic mode each issue is validated LOCALLY before committing. The remote
# pipeline runs once, on the single epic PR.
#
# Run as: bash .pi/scripts/ci/epic-gate.sh [--full]
#   default: preflight + architecture + tests (fast, per issue)
#   --full:  also security + canonical + integration (before the epic PR)
# ============================================================================
set -uo pipefail
FULL=0
[ "${1:-}" = "--full" ] && FULL=1
FAILED=0

run() {
	local name="$1"; shift
	echo ""
	echo "── $name"
	if bash "$@" ; then
		echo "   ✅ $name"
	else
		echo "   ❌ $name"
		FAILED=1
	fi
}

[ -f ".pi/scripts/ci/run_preflight.sh" ] && run "preflight" .pi/scripts/ci/run_preflight.sh
[ -f ".pi/scripts/validate-architecture.sh" ] && run "architecture" .pi/scripts/validate-architecture.sh
[ -f ".pi/scripts/validate-tests.sh" ] && run "tests" .pi/scripts/validate-tests.sh
if [ "$FULL" = "1" ]; then
	[ -f ".pi/scripts/validate-security.sh" ] && run "security" .pi/scripts/validate-security.sh
	[ -f ".pi/scripts/validate-canonical.sh" ] && run "canonical" .pi/scripts/validate-canonical.sh
	[ -f ".pi/scripts/validate-integration.sh" ] && run "integration" .pi/scripts/validate-integration.sh
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
	echo "✅ Epic gate passed${FULL:+ (full)} — safe to commit"
	exit 0
fi
echo "❌ Epic gate failed — fix before committing (no PR needed)"
exit 1
