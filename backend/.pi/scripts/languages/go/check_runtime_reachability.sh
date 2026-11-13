#!/usr/bin/env bash
# ============================================================================
# check_runtime_reachability.sh — Go (ADR-009)
#
# Every service file under src/<module>/application/ must be referenced from
# production code OUTSIDE its own module and OUTSIDE tests. Candidates: the
# file stem (snake), its PascalCase type name, and the separator-stripped
# form (case-insensitive).
# Usage: bash check_runtime_reachability.sh [--root <dir>]
# Exit:  0 all reachable ; 1 dead service(s)
# ============================================================================
set -uo pipefail
ROOT="$(pwd)"
if [ "${1:-}" = "--root" ] && [ -n "${2:-}" ]; then ROOT="$2"; fi
cd "$ROOT" || exit 1
VIOLATIONS=0
[ -d src ] || { echo "runtime-reachability (go): no src/"; exit 0; }

while IFS= read -r svc; do
    [ -n "$svc" ] || continue
    mod="$(echo "$svc" | sed 's|^src/||; s|/application/.*||')"
    stem="$(basename "$svc" .go)"
    pascal="$(echo "$stem" | python3 -c 'import sys; s=sys.stdin.read().strip(); print("".join(w.capitalize() for w in s.split("_")) if s else "")' 2>/dev/null || echo "$stem")"
    compact="$(echo "$stem" | tr -d '_-')"
    refs="$(grep -rliE "\b(${pascal}|${stem}|${compact})\b" src 2>/dev/null | grep -vE "_test\.go$|/tests?/|/test/" | grep -v "^src/${mod}/" | grep -v "^${svc}$" | grep -cv '^$' || true)"
    if [ "${refs:-0}" -eq 0 ]; then
        echo "$svc: [runtime-reachability] application service has no production caller outside its module (tests-only callers don't count — ADR-009)"
        VIOLATIONS=$((VIOLATIONS + 1))
    fi
done < <(find src -path "*/application/*.go" -type f 2>/dev/null | grep -vE "_test\.go$" || true)

if [ "$VIOLATIONS" -gt 0 ]; then echo "runtime-wiring (go): ${VIOLATIONS} unwired service(s)" >&2; exit 1; fi
echo "runtime-reachability (go): all application services reachable from production code"
exit 0
