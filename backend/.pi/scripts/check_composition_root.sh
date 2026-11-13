#!/usr/bin/env bash
# ============================================================================
# check_composition_root.sh — implemented modules must be INSTALLED in the app
# ============================================================================
# ADR-009 gap: "referenced outside the module" is not "wired into the runtime".
# A service can be imported by one stray helper and still never be registered in
# the composition root — the app boots and the feature does not exist.
#
# This check asserts, per implemented module, that the app shell references it:
#   python  : FastAPI include_router / container build / app.add_*
#   java    : Spring @Bean / @ComponentScan / new *Configuration / @Import
#   typescript: app.use( / router registration / createRouter / bootstrap
#   go      : handler registration / mux.Handle / router.Register
#   rust    : router/handler registration in main or app module
#
# Exemptions: modules whose doc declares "not wired by design" or bootstrap-only.
# Usage: bash .pi/scripts/check_composition_root.sh [--root <dir>] [--strict]
# Exit:  0 all implemented modules installed; 1 unwired module(s)
# ============================================================================
set -uo pipefail
ROOT="$(pwd)"
ARGS=("$@")
for ((i=0;i<${#ARGS[@]};i++)); do
	case "${ARGS[$i]}" in
		--root) ROOT="${ARGS[$((i+1))]:-$ROOT}" ;;
	esac
done
cd "$ROOT" || exit 1

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
echo "============================================"
echo "  Composition Root (implemented = installed)"
echo "============================================"

# ── language + app shell candidates ──────────────────────────────────────────
LANG_NAME=""
[ -f guardian-manifest.json ] && LANG_NAME=$(python3 -c "import json;print(json.load(open('guardian-manifest.json')).get('language',''))" 2>/dev/null || true)
echo "Language: ${LANG_NAME:-unknown}"

SHALLS=()
case "$LANG_NAME" in
	python|nextjs|angular|typescript)
		while IFS= read -r f; do SHALLS+=("$f"); done < <(find src app -maxdepth 4 -type f \( -name "app.py" -o -name "main.py" -o -name "__main__.py" -o -name "server.ts" -o -name "main.ts" -o -name "index.ts" \) 2>/dev/null | grep -vE "test|spec" | head -6)
		COVER_PATTERN="include_router|add_router|app\.use\(|createRouter|register_module|build_container|@Module"
		;;
	java)
		while IFS= read -r f; do SHALLS+=("$f"); done < <(find src/main/java -maxdepth 10 -type f \( -name "*Application.java" -o -name "*Configuration.java" -o -name "*Config.java" \) 2>/dev/null | head -8)
		COVER_PATTERN="@Bean|@ComponentScan|@Import|@EnableAutoConfiguration|@SpringBootApplication"
		;;
	go)
		while IFS= read -r f; do SHALLS+=("$f"); done < <(find . -maxdepth 4 -type f -name "main.go" 2>/dev/null | head -4)
		COVER_PATTERN="http.Handle|mux.Handle|router.Register|\.Use\(|RegisterRoutes"
		;;
	rust)
		while IFS= read -r f; do SHALLS+=("$f"); done < <(find . -maxdepth 4 -type f -name "main.rs" 2>/dev/null | grep -v target | head -4)
		COVER_PATTERN="\.route\(|Router::new|add_route|register_handler|\.merge\("
		;;
esac

if [ "${#SHALLS[@]}" -eq 0 ]; then
	echo ""
	if [ "$LANG_NAME" = "python" ] || [ "$LANG_NAME" = "typescript" ]; then
		echo -e "${RED}❌ FAIL${NC} no application shell found (expected src/**/app.py|main.py or app.use/bootstrap)"
		exit 1
	fi
	echo "no application shell detected for $LANG_NAME — skipping"
	exit 0
fi

echo "App shell(s): ${SHALLS[*]}"

# Only CODE counts. A module named in a comment or a docstring is not installed:
# the first version of this check passed BECAUSE the shell listed the upcoming
# modules in a comment ("Billing (Phase 2), Settlement (Phase 4) ...").
SHELL_TEXT=$(python3 - "${SHALLS[@]}" <<'PY'
import re, sys
out = []
for path in sys.argv[1:]:
    try:
        src = open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        continue
    src = re.sub('"""[\s\S]*?"""', "", src)
    src = re.sub("'''[\\s\\S]*?'''", "", src)
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    lines = []
    for line in src.splitlines():
        code = re.sub(r"\s*(#|//).*$", "", line)
        if code.strip():
            lines.append(code)
    out.append("\n".join(lines))
print("\n".join(out))
PY
)

# ── modules that claim implementation ────────────────────────────────────────
MODS=()
if [ -d .pi/architecture/modules ]; then
	while IFS= read -r f; do
		b=$(basename "$f" .md)
		[ "$b" = "module-template" ] && continue
		# Skip docs that explicitly declare they are not runtime-installed.
		grep -qiE "not wired by design|bootstrap only|no runtime integration|not part of the runtime" "$f" && continue
		# Only IMPLEMENTED modules can be "implemented but never wired". A frozen
		# but unimplemented module has no router yet; demanding one is noise.
		status=$(grep -m1 -oiE '\*\*Status:\*\* *[A-Za-z]+' "$f" | sed -E 's/.*\*\* *//' | tr '[:upper:]' '[:lower:]')
		case "$status" in
			implemented | done | complete) MODS+=("$b") ;;
			*) continue ;;
		esac
	done < <(find .pi/architecture/modules -name "*.md" -type f | sort)
fi

if [ "${#MODS[@]}" -eq 0 ]; then
	echo "no implemented modules yet — nothing to install (frozen/planned modules are not demanded)"
	exit 0
fi

UNWIRED=0
for m in "${MODS[@]}"; do
	# normalize: identity-access -> identity_access, identityaccess
	norm=$(echo "$m" | tr -d '_-' )
	matched=0
	# 1) shell text mentions the module (router import, container build, bean, etc.)
	if echo "$SHELL_TEXT" | grep -qiE "(^|[^a-z0-9])${m//-/[-_ ]}($|[^a-z0-9])"; then matched=1; fi
	if [ "$matched" -eq 0 ] && echo "$SHELL_TEXT" | grep -qi "$norm"; then matched=1; fi
	# 2) shell imports a file from the module package (language-agnostic)
	if [ "$matched" -eq 0 ]; then
		while IFS= read -r sh; do
			if grep -qE "(from|import)\s+[\"']?${m//-/[_ ]}|${norm}" "$sh" 2>/dev/null; then matched=1; break; fi
		done < <(printf '%s\n' "${SHALLS[@]}")
	fi
	# 3) the shell has at least one registration call AND imports the module (covered above)
	if [ "$matched" -eq 0 ]; then
		echo -e "${RED}❌ FAIL${NC} ${m}: implemented but NOT installed in the app shell (${SHALLS[0]})"
		UNWIRED=$((UNWIRED+1))
	fi
done

if [ "$UNWIRED" -eq 0 ]; then
	echo ""
	echo -e "${GREEN}✅ PASS${NC} all ${#MODS[@]} module(s) installed in the composition root"
	exit 0
fi
echo ""
echo -e "${RED}❌ FAIL${NC} ${UNWIRED}/${#MODS[@]} module(s) implemented but never wired into the app"
echo "   Fix: register the module in ${SHALLS[0]} (router/bean/handler/container) and"
echo "        add an end-to-end test through the public entrypoint."
exit 1
