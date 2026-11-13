#!/usr/bin/env bash
# ============================================================================
# check_runtime_reachability.sh — TypeScript (ADR-009)
#
# Every service file under src/<module>/application/ must be referenced from
# production code outside its own module and outside tests. References inside
# the service's own module or in *.test.ts / __tests__ do not count.
#
# Usage: bash check_runtime_reachability.sh [--root <dir>]
# Exit:  0 all reachable ; 1 dead service(s)
# ============================================================================
set -uo pipefail
ROOT="$(pwd)"
if [ "${1:-}" = "--root" ] && [ -n "${2:-}" ]; then ROOT="$2"; fi
cd "$ROOT" || exit 1

VIOLATIONS=0
[ -d src ] || { echo "runtime-reachability (ts): no src/"; exit 0; }

while IFS= read -r svc; do
    [ -n "$svc" ] || continue
    case "$svc" in
        */*test*/|*.test.ts|*.spec.ts) continue ;;
    esac
    mod="$(echo "$svc" | sed 's|^src/||; s|/application/.*||')"
    name="$(basename "$svc" .ts)"
    # production references: whole src, excluding tests and the service's own module
    refs="$(grep -rl "\b${name}\b" src 2>/dev/null | grep -vE "/__tests__/|\.(test|spec)\.ts$|/tests?/|^src/${mod}/" | grep -v "^src/${mod}/" | grep -cv '^$' || true)"
    # also drop the file itself from any residual (own-module exclusion above already does)
    if [ "${refs:-0}" -eq 0 ]; then
        echo "$svc: [runtime-reachability] application service has no production caller outside its module (tests-only callers don't count — ADR-009)"
        VIOLATIONS=$((VIOLATIONS + 1))
    fi
done < <(find src -path "*/application/*.ts" -type f 2>/dev/null || true)

if [ "$VIOLATIONS" -gt 0 ]; then
    echo "runtime-wiring (ts): ${VIOLATIONS} unwired service(s)" >&2
    exit 1
fi
echo "runtime-reachability (ts): all application services reachable from production code"
exit 0
