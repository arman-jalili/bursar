#!/usr/bin/env bash
# ============================================================================
# check_runtime_reachability.sh — Java (ADR-009)
#
# Every application-layer class under src/<module>/application/ must be
# referenced from production code OUTSIDE its own module and OUTSIDE tests.
# Java file == public class: the candidate is the file stem.
# Usage: bash check_runtime_reachability.sh [--root <dir>]
# Exit:  0 all reachable ; 1 dead service(s)
# ============================================================================
set -uo pipefail
ROOT="$(pwd)"
if [ "${1:-}" = "--root" ] && [ -n "${2:-}" ]; then ROOT="$2"; fi
cd "$ROOT" || exit 1
VIOLATIONS=0
[ -d src ] || { echo "runtime-reachability (java): no src/"; exit 0; }

while IFS= read -r svc; do
    [ -n "$svc" ] || continue
    mod="$(echo "$svc" | sed 's|^src/||; s|/application/.*||')"
    stem="$(basename "$svc" .java)"
    refs="$(grep -rl "\b${stem}\b" src 2>/dev/null | grep -vE "src/test/|/tests?/|Test[s]?\.java$" | grep -v "^src/${mod}/" | grep -v "^${svc}$" | grep -cv '^$' || true)"
    if [ "${refs:-0}" -eq 0 ]; then
        echo "$svc: [runtime-reachability] application service has no production caller outside its module (tests-only callers don't count — ADR-009)"
        VIOLATIONS=$((VIOLATIONS + 1))
    fi
done < <(find src -path "*/application/*.java" -type f 2>/dev/null | grep -vE "Test[s]?\.java$" || true)

if [ "$VIOLATIONS" -gt 0 ]; then echo "runtime-wiring (java): ${VIOLATIONS} unwired service(s)" >&2; exit 1; fi
echo "runtime-reachability (java): all application services reachable from production code"
exit 0
