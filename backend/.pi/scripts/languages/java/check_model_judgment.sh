#!/usr/bin/env bash
# ============================================================================
# check_model_judgment.sh — Java (ADR-008/009)
# Deterministic hard gates:
#   dip-domain           domain/ imports jakarta/javax.persistence, springframework, hibernate
#   txn-placement        @Transactional outside the application layer
#   interface-ownership  (tactical) infra repository impls need a domain/-owned interface
#   adapter-purity       (adapter modules) model code in generic subdomains
#   web-layer-leak       interfaces/ (controllers) importing CONCRETE infrastructure
#                        implementations (Jdbc*/Local*/InMemory*/... or, in tactical
#                        modules, any .infrastructure. type)
#
# Layout-aware: supports both src/<module>/{domain,...} and Maven
# src/main/java/<group>/<module>/{domain,...}. Module docs drive depth rules.
# Usage: bash check_model_judgment.sh [--root <dir>]
# ============================================================================
set -uo pipefail
ROOT="$(pwd)"
if [ "${1:-}" = "--root" ] && [ -n "${2:-}" ]; then ROOT="$2"; fi
cd "$ROOT" || exit 1

VIOLATIONS=0
report() { echo "$1:$2: [$3] $4"; VIOLATIONS=$((VIOLATIONS + 1)); }

is_prod_java() {
    case "$1" in
        */test/*|*/src/test/*) return 1 ;;
        *Test.java|*Tests.java) return 1 ;;
    esac
    return 0
}

# Resolve a module's source root for a module doc (kebab name).
# 1) legacy: src/<module>/
# 2) maven:  src/main/java/<group>/<sanitized-module>/ (sanitized = lower, no separators)
resolve_module_root() { # doc_name
    local doc_name="$1"
    local norm legacy
    norm="$(echo "$doc_name" | sed 's/^module[-_]//' | tr '[:upper:]' '[:lower:]' | tr '-' '_')"
    legacy="src/$(echo "$doc_name" | sed 's/^module[-_]//' | tr '[:upper:]' '[:lower:]' | tr '-' '_')"
    if [ -d "$legacy" ]; then echo "$legacy"; return; fi
    if [ -d "src/main/java" ]; then
        local sanitized
        sanitized="$(echo "$doc_name" | tr '[:upper:]' '[:lower:]' | tr -d '_-')"
        # match <group>/<sanitized> dir anywhere under the java tree (module package root)
        local cand
        while IFS= read -r cand; do
            [ -n "$cand" ] || continue
            if [ "$(basename "$cand")" = "$sanitized" ]; then echo "$cand"; return; fi
        done < <(find "src/main/java" -type d -name "$sanitized" 2>/dev/null | head -3 || true)
    fi
    echo ""
}

# ── Rule 2: DIP — domain imports framework types ─────────────────────────────
while IFS= read -r f; do
    [ -n "$f" ] || continue
    is_prod_java "$f" || continue
    case "$f" in
        */domain/*)
            while IFS=: read -r ln rest; do
                case "$rest" in
                    *jakarta.persistence*|*javax.persistence*|*org.springframework*|*org.hibernate*)
                        imp="$(echo "$rest" | sed 's/^[[:space:]]*import[[:space:]]*//; s/;//')"
                        report "$f" "$ln" "dip-domain" "domain layer imports framework type: $imp"
                        ;;
                esac
            done < <(grep -nE '^[[:space:]]*import[[:space:]]+' "$f" || true)
            ;;
    esac
done < <(find src -type f -name "*.java" 2>/dev/null || true)

# ── Rule 1: transactions only in the application layer ───────────────────────
while IFS= read -r f; do
    [ -n "$f" ] || continue
    is_prod_java "$f" || continue
    case "$f" in
        */application/*) continue ;;
    esac
    while IFS=: read -r ln rest; do
        case "$rest" in
            *@Transactional*)
                report "$f" "$ln" "txn-placement" "@Transactional must live on application-layer services (transaction boundaries)"
                ;;
        esac
    done < <(grep -nE '@Transactional' "$f" || true)
done < <(find src -type f -name "*.java" 2>/dev/null || true)

# ── Rules 3–5: module-doc depth-driven checks ─────────────────────────────────
if [ -d ".pi/architecture/modules" ]; then
    for doc in .pi/architecture/modules/*.md; do
        [ -f "$doc" ] || continue
        doc_name="$(basename "$doc" .md)"
        [ "$doc_name" = "module-template" ] && continue
        depth="$(grep -m1 '^\*\*Modeling Depth:\*\*' "$doc" | sed 's/.*\*\*Modeling Depth:\*\* *//' | cut -d' ' -f1 || true)"
        match_dir="$(resolve_module_root "$doc_name")"
        [ -n "$match_dir" ] || continue

        # interfaces layer (http/web) — concrete infrastructure implementations leak
        while IFS= read -r f; do
            [ -n "$f" ] || continue
            is_prod_java "$f" || continue
            case "$f" in
                */interfaces/*)
                    while IFS=: read -r ln rest; do
                        case "$rest" in
                            *infrastructure.*)
                                cls="$(echo "$rest" | sed 's/^[[:space:]]*import[[:space:]]*//; s/;//' | awk -F. '{print $NF}')"
                                # concrete impl markers (Jdbc*/Jpa*/Local*/InMemory*/Hibernate*/...);
                                # in tactical modules ANY .infrastructure. import from web layer is a leak
                                case "$cls" in
                                    Jdbc*|Jpa*|Local*|InMemory*|Hibernate*|Sql*)
                                        report "$f" "$ln" "web-layer-leak" "web layer imports CONCRETE infrastructure impl $cls — depend on a port/interface via the application layer"
                                        ;;
                                esac
                                if [ "$depth" = "tactical" ]; then
                                    case "$cls" in
                                        *Repository*|*Port*|*Gateway*|*Service*|*Config*|*Store*)
                                            : ;;
                                        *)
                                            report "$f" "$ln" "web-layer-leak" "tactical module: web layer imports infrastructure type $cls — go through the application layer"
                                            ;;
                                    esac
                                fi
                                ;;
                        esac
                    done < <(grep -nE '^[[:space:]]*import[[:space:]]+' "$f" || true)
                    ;;
            esac
        done < <(find "$match_dir/interfaces" -type f -name "*.java" 2>/dev/null || true)

        if [ "$depth" = "adapter" ]; then
            for layer in domain application; do
                while IFS= read -r f; do
                    [ -n "$f" ] || continue
                    is_prod_java "$f" || continue
                    report "$f" "1" "adapter-purity" "generic subdomain '${doc_name}' must not contain ${layer}/ model code (ADR-008)"
                done < <(find "$match_dir/$layer" -type f -name "*.java" 2>/dev/null || true)
            done
        elif [ "$depth" = "tactical" ]; then
            # interface-ownership: infra repository impls need a domain/-owned
            # interface. Build candidate names by stripping Impl suffix and
            # Jpa/Jdbc/Hibernate/Spring prefixes, then search the domain layer.
            while IFS= read -r impl; do
                [ -n "$impl" ] || continue
                stem="$(basename "$impl" .java)"
                names="$stem"
                for n in "${stem%Impl}" "${stem#Jpa}" "${stem#Jdbc}" "${stem#Hibernate}" "${stem#Spring}"; do
                    [ -n "$n" ] || continue
                    case " $names " in *" $n "*) ;; *) names="$names $n" ;; esac
                done
                # infix markers: MoneyOutIntentJdbcRepository -> MoneyOutIntentRepository
                for marker in Jpa Jdbc Hibernate Spring; do
                    n="${stem//$marker/}"
                    [ -n "$n" ] || continue
                    case " $names " in *" $n "*) ;; *) names="$names $n" ;; esac
                done
                found=""
                for n in $names; do
                    if grep -rqiE "interface ${n}\\b|class ${n}\\b" "$match_dir/domain" --include="*.java" 2>/dev/null; then
                        found=1; break
                    fi
                done
                if [ -z "$found" ]; then
                    compact="$(echo "$stem" | tr -d '_-')"
                    if [ -z "$compact" ] || ! grep -rqil --include="*.java" "$compact" "$match_dir/domain" 2>/dev/null; then
                        report "$impl" "1" "interface-ownership" "repository implementation without a domain/-owned interface (${stem})"
                    fi
                fi
            done < <(find "$match_dir/infrastructure" -type f \( -iname "*Repository*.java" \) 2>/dev/null || true)
        fi
    done
fi

if [ "$VIOLATIONS" -gt 0 ]; then
    echo "model-judgment (java): ${VIOLATIONS} violation(s)" >&2
    exit 1
fi
echo "model-judgment (java): all gates passed (dip-domain, txn-placement, interface-ownership, adapter-purity, web-layer-leak)"
exit 0
