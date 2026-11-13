#!/usr/bin/env bash
# ============================================================================
# check_language_consistency.sh — architecture docs must use the project language
# ============================================================================
# Catches two failure modes:
#   1. Scaffold emitting stubs in the wrong language (historically Rust in every
#      project, regardless of manifest language).
#   2. An enrichment/codegen agent copying a foreign-language sample.
#
# Fences for "infrastructure" languages that are legitimately language-agnostic
# (json, yaml, toml, bash, sql, mermaid, text, dockerfile, http, diff, ini) are
# always allowed; markdown is allowed too.
#
# Usage: bash .pi/scripts/check_language_consistency.sh [--strict]
#   --strict  also treat other framework languages (angular/nextjs) as foreign
# ============================================================================
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0
pass() { echo -e "${GREEN}✅ PASS${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}❌ FAIL${NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}⚠️  WARN${NC} $1"; WARN=$((WARN+1)); }

STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1

echo "============================================"
echo "  Language Consistency (architecture docs)"
echo "============================================"

# ── Resolve project language ────────────────────────────────────────────────
LANG_NAME=""
if [ -f "guardian-manifest.json" ]; then
	LANG_NAME=$(python3 -c "import json;print(json.load(open('guardian-manifest.json')).get('language',''))" 2>/dev/null || true)
fi
if [ -z "$LANG_NAME" ] && [ -f ".pi/guardian-manifest.json" ]; then
	LANG_NAME=$(python3 -c "import json;print(json.load(open('.pi/guardian-manifest.json')).get('language',''))" 2>/dev/null || true)
fi
if [ -z "$LANG_NAME" ]; then
	echo "no manifest language — skipping"
	exit 0
fi
echo "Project language: $LANG_NAME"
echo ""

case "$LANG_NAME" in
	typescript|nextjs|angular) EXPECTED="typescript|tsx|ts|javascript|jsx|js" ;;
	python)                    EXPECTED="python|py" ;;
	rust)                      EXPECTED="rust" ;;
	go)                        EXPECTED="go" ;;
	java)                      EXPECTED="java" ;;
	*)                         EXPECTED="" ;;
esac

if [ -z "$EXPECTED" ]; then
	echo "unsupported language '$LANG_NAME' — skipping"
	exit 0
fi

ALL_FENCES="typescript|tsx|ts|javascript|jsx|js|python|py|rust|go|java|kotlin|kt|csharp|cs|ruby|rb|php|swift|cpp|c\+\+|c|scala|elixir|dart"
ALLOWED_NEUTRAL="json|jsonc|yaml|yml|toml|bash|sh|shell|zsh|sql|mermaid|text|txt|plaintext|dockerfile|docker|http|diff|ini|properties|xml|html|css|scss|makefile|cmake|gradle|protobuf|proto|csv|regex|"

is_expected() {
	local f="$1"
	[ -z "$f" ] && return 1                       # bare ``` with no language
	case "$EXPECTED" in
		*"|$f|"*|"$f|"*) return 0 ;;
	esac
	# substring match for multi-alias lists
	echo "$EXPECTED" | tr '|' '\n' | grep -qx "$f" && return 0
	return 1
}

is_neutral() {
	local f="$1"
	[ -z "$f" ] && return 0
	echo "$ALLOWED_NEUTRAL" | tr '|' '\n' | grep -qx "$f"
}

ROOT=".pi/architecture"
[ -d "$ROOT" ] || { echo "no $ROOT — nothing to check"; exit 0; }

FILES=$(find "$ROOT" -name "*.md" -type f 2>/dev/null | grep -v "/modules/module-template.md$")
MISMATCHES=0
CHECKED=0
for doc in $FILES; do
	CHECKED=$((CHECKED+1))
	# Collect fenced block languages
	fences=$(grep -oE '^```[a-zA-Z0-9_+-]*' "$doc" 2>/dev/null | sed 's/^```//' | sort -u)
	[ -z "$fences" ] && continue
	bad=""
	for f in $fences; do
		lower=$(echo "$f" | tr '[:upper:]' '[:lower:]')
		if is_neutral "$lower"; then continue; fi
		if is_expected "$lower"; then continue; fi
		# A fence that is a known programming language but not this project's
		if echo "$lower" | grep -qE "^($ALL_FENCES)$"; then
			bad="$bad $lower"
		elif [ "$STRICT" = "1" ]; then
			bad="$bad $lower"
		fi
	done
	if [ -n "$bad" ]; then
		fail "$doc uses foreign code fence(s):$(echo "$bad" | tr ' ' '\n' | sed '/^$/d' | sort -u | sed 's/^/ /' | tr '\n' ',' | sed 's/,$//')  (project: $LANG_NAME)"
		MISMATCHES=$((MISMATCHES+1))
	fi
done

if [ "$MISMATCHES" -eq 0 ]; then
	pass "$CHECKED architecture doc(s) use $LANG_NAME (no foreign code fences)"
else
	fail "$MISMATCHES of $CHECKED architecture doc(s) contain foreign-language code samples"
fi

echo ""
echo "============================================"
echo "  Summary"
echo "============================================"
echo "  Passed: $PASS  Failed: $FAIL  Warnings: $WARN"
[ "$FAIL" -eq 0 ] && exit 0
exit 1
