#!/usr/bin/env bash
# ============================================================================
# check_model_judgment.sh — Go (ADR-008/009)
# Deterministic hard gates:
#   dip-domain           domain/ imports gorm/sqlx/gin/echo
#   txn-placement        sql.Tx / BeginTx outside application/
#   interface-ownership  (tactical) infra adapters without a domain interface
#   adapter-purity       (adapter modules) model code in generic subdomains
# Usage: bash check_model_judgment.sh [--root <dir>]
# ============================================================================
set -uo pipefail
ROOT="$(pwd)"
if [ "${1:-}" = "--root" ] && [ -n "${2:-}" ]; then ROOT="$2"; fi
cd "$ROOT" || exit 1
VIOLATIONS=0
report() { echo "$1:$2: [$3] $4"; VIOLATIONS=$((VIOLATIONS + 1)); }
[ -d src ] || { echo "model-judgment (go): no src/"; exit 0; }

while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in */domain/*)
        while IFS=: read -r ln rest; do
            case "$rest" in
                *gorm.io*|*database/sql*|*sqlx*|*gin-gonic*|*labstack*|*uptrace/bun*)
                    report "$f" "$ln" "dip-domain" "domain imports persistence/web framework: $rest" ;;
            esac
        done < <(grep -nE '^\s*("|_ "|import )' "$f" | grep -E 'gorm|sqlx|database/sql|gin-gonic|labstack|bun' || true) ;;
    esac
    case "$f" in */application/*) ;; *)
        if grep -qE "sql\.Tx|BeginTx|\.Commit\(\)" "$f" 2>/dev/null; then
            report "$f" "1" "txn-placement" "transaction handling outside application layer"
        fi ;;
    esac
done < <(find src -type f -name "*.go" 2>/dev/null | grep -vE "_test\.go$|/tests?/" || true)

if [ -d ".pi/architecture/modules" ]; then
    for doc in .pi/architecture/modules/*.md; do
        [ -f "$doc" ] || continue
        doc_name="$(basename "$doc" .md)"
        depth="$(grep -m1 '^\*\*Modeling Depth:\*\*' "$doc" | sed 's/.*\*\*Modeling Depth:\*\* *//' | cut -d' ' -f1 || true)"
        docnorm="$(echo "$doc_name" | sed 's/^module[-_]//' | tr '[:upper:]' '[:lower:]' | tr '-' '_')"
        match_dir=""
        while IFS= read -r d; do
            norm="$(basename "$d" | tr '[:upper:]' '[:lower:]' | tr '-' '_')"
            if [ "$norm" = "$docnorm" ]; then match_dir="$d"; break; fi
        done < <(find src -mindepth 1 -maxdepth 1 -type d 2>/dev/null || true)
        [ -n "$match_dir" ] || continue
        if [ "$depth" = "adapter" ]; then
            for layer in domain application; do
                while IFS= read -r f; do [ -n "$f" ] || continue; report "$f" "1" "adapter-purity" "generic subdomain '${doc_name}' must not contain ${layer}/ model code (ADR-008)"; done < <(find "$match_dir/$layer" -type f -name "*.go" 2>/dev/null || true)
            done
        elif [ "$depth" = "tactical" ]; then
            while IFS= read -r impl; do
                [ -n "$impl" ] || continue
                simple="$(basename "$impl" .go)"
                stem="$(echo "$simple" | sed -E 's/Impl$//;s/impl$//')"
                if ! grep -rqiE "type ${stem} interface|type ${simple} interface|${stem}" "$match_dir/domain" 2>/dev/null; then
                    compact="$(printf '%s' "$simple" | tr -d '_-')"
                    if [ -z "$compact" ] || ! grep -rqil "$compact" "$match_dir/domain" 2>/dev/null; then
                        report "$impl" "1" "interface-ownership" "adapter without a domain/-owned interface (${simple})"
                    fi
                fi
            done < <(find "$match_dir/infrastructure" -type f -name "*.go" 2>/dev/null || true)
        fi
    done
fi

if [ "$VIOLATIONS" -gt 0 ]; then echo "model-judgment (go): ${VIOLATIONS} violation(s)" >&2; exit 1; fi
echo "model-judgment (go): all gates passed (dip-domain, txn-placement, interface-ownership, adapter-purity)"
exit 0
