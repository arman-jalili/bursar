#!/usr/bin/env bash
# ============================================================================
# check_model_judgment.sh — TypeScript (ADR-008/009)
# Deterministic hard gates, mirrors the Java four:
#   dip-domain           domain/ imports framework/persistence types
#   txn-placement        transaction/UnitOfWork boundaries outside application/
#   interface-ownership  (tactical) infra adapters without a domain/-owned interface
#   adapter-purity       (adapter modules) model code in generic subdomains
# Usage: bash check_model_judgment.sh [--root <dir>]
# ============================================================================
set -uo pipefail
ROOT="$(pwd)"
if [ "${1:-}" = "--root" ] && [ -n "${2:-}" ]; then ROOT="$2"; fi
cd "$ROOT" || exit 1

VIOLATIONS=0
report() { echo "$1:$2: [$3] $4"; VIOLATIONS=$((VIOLATIONS + 1)); }

[ -d src ] || { echo "model-judgment (ts): no src/"; exit 0; }
while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in */*test*/|*.test.ts|*.spec.ts) continue ;; esac
    # dip-domain
    case "$f" in */domain/*)
        while IFS=: read -r ln rest; do
            case "$rest" in
                *typeorm*|*prisma*|*@nestjs*|*express*|*sequelize*)
                    report "$f" "$ln" "dip-domain" "domain imports framework: $(echo "$rest" | sed 's/^import //; s/;//')" ;;
            esac
        done < <(grep -nE "^import |require\\(" "$f" || true) ;;
    esac
    # txn-placement: transaction/UnitOfWork usage outside application/
    case "$f" in */application/*) ;; *)
        if grep -qE "transaction|unitOfWork|beginTransaction|\.manager\.(save|transaction)" "$f" 2>/dev/null; then
            report "$f" "1" "txn-placement" "transaction/UnitOfWork logic outside application layer"
        fi ;;
    esac
done < <(find src -type f -name "*.ts" 2>/dev/null || true)

# module-doc depth rules (same layout as Java)
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
                while IFS= read -r f; do [ -n "$f" ] || continue; report "$f" "1" "adapter-purity" "generic subdomain '${doc_name}' must not contain ${layer}/ model code (ADR-008)"; done < <(find "$match_dir/$layer" -type f -name "*.ts" 2>/dev/null || true)
            done
        elif [ "$depth" = "tactical" ]; then
            while IFS= read -r impl; do
                [ -n "$impl" ] || continue
                simple="$(basename "$impl" .ts)"
                cands="$simple
$(echo "$simple" | sed -E 's/Impl$//')"
                found=""
                while IFS= read -r cand; do
                    [ -n "$cand" ] || continue
                    if grep -rqiE "interface ${cand}\\b|abstract class ${cand}\\b|${cand}" "$match_dir/domain" 2>/dev/null; then found=1; break; fi
                done <<< "$cands"
                # separator-stripped fallback: invoice-repository <-> InvoiceRepository
                if [ -z "$found" ]; then
                    compact="$(printf '%s' "$simple" | tr -d '_-')"
                    if [ -n "$compact" ] && grep -rqil "$compact" "$match_dir/domain" 2>/dev/null; then found=1; fi
                fi
                if [ -z "$found" ]; then report "$impl" "1" "interface-ownership" "adapter without a domain/-owned interface (${simple})"; fi
            done < <(find "$match_dir/infrastructure" -type f \( -iname "*repository*.ts" -o -iname "*gateway*.ts" -o -iname "*service*.ts" \) 2>/dev/null || true)
        fi
    done
fi

if [ "$VIOLATIONS" -gt 0 ]; then echo "model-judgment (ts): ${VIOLATIONS} violation(s)" >&2; exit 1; fi
echo "model-judgment (ts): all gates passed (dip-domain, txn-placement, interface-ownership, adapter-purity)"
exit 0
