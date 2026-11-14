#!/usr/bin/env bash
# ============================================================================
# validate-shell-exit-status.sh — a passing path must not exit non-zero
# ============================================================================
# The bug class: an arithmetic command used as a *statement*.
#
#   set -e; x=0; x=$((x + 1)); echo survived
#     bash 3.2 (macOS) → exit 0, prints "survived"
#     bash 4.4 / 5.x   → exit 1, prints nothing
#
# Two shapes are caught:
#   1. a standalone arithmetic command in a script that enables errexit
#   2. the same command as the tail of a one-line function body — there the
#      *function* returns 1, which errexit treats as a failed command on every
#      shell: `log_pass() { echo ok; PASS=$((PASS + 1)); }` ends the script on macOS too.
#
# The fix is the assignment form, `X=$((X + 1))`, which always returns 0 and
# does not swallow a real failure (unlike `x=$((x + 1)) || true`).
#
# Usage: bash .pi/scripts/validate-shell-exit-status.sh [root] [--self-test]
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Resolve the project root: the nearest ancestor of this script that looks like
# a project (has .git or package.json). Works whether the script is invoked from
# the canonical tree (templates/pi/scripts) or the shipped copy (.pi/scripts).
resolve_root() {
	local d
	d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
	while [ "$d" != "/" ]; do
		if [ -e "$d/.git" ] || [ -e "$d/package.json" ]; then
			echo "$d"
			return
		fi
		d="$(dirname "$d")"
	done
	echo "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
}
RESOLVED_ROOT="$(resolve_root)"
ROOT="${1:-$RESOLVED_ROOT}"

[ "$ROOT" = "--self-test" ] && ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SELFTEST=0
for a in "$@"; do [ "$a" = "--self-test" ] && SELFTEST=1; done

ARITH='\(\([[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*(\+\+|--)[[:space:]]*\)\)'
STANDALONE_RE="^[[:space:]]*${ARITH}[[:space:]]*;?[[:space:]]*(#.*)?$"
FUNC_TAIL_RE="^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*\(\)[[:space:]]*\{.*;[[:space:]]*${ARITH}[[:space:]]*;[[:space:]]*\}[[:space:]]*(#.*)?$"
ERREXIT_RE='^[[:space:]]*set[[:space:]]+-[a-zA-Z]*e|set[[:space:]]+-o[[:space:]]+errexit'

scan() {
	# $1 = root to scan
	local root="$1"
	local offenders=0
	while IFS= read -r f; do
		case "$f" in */node_modules/* | */target/* | */.git/*) continue ;; esac
		# Only files that enable errexit are in scope.
		grep -qE "$ERREXIT_RE" "$f" 2>/dev/null || continue
		local n=0
		while IFS= read -r line; do
			n=$((n + 1))
			if [[ "$line" =~ $STANDALONE_RE ]] || [[ "$line" =~ $FUNC_TAIL_RE ]]; then
				if [ "$offenders" -eq 0 ]; then
					echo "Arithmetic command used as a statement (returns 1 when the value is 0):" >&2
				fi
				offenders=$((offenders + 1))
				echo "  ${f#"$root"/}:$n: $(echo "$line" | sed 's/^[[:space:]]*//')" >&2
			fi
		done <"$f"
	done < <(find "$root" -name '*.sh' -not -path '*/node_modules/*' -not -path '*/target/*' -not -path '*/.git/*' 2>/dev/null)

	if [ "$offenders" -gt 0 ]; then
		echo "" >&2
		echo "  Use the assignment form, which always returns 0:" >&2
		echo "    X=\$((X + 1))     (not  ((X++))  and not  ((X++)) || true)" >&2
		return 1
	fi
	return 0
}

if [ "$SELFTEST" -eq 1 ]; then
	TD="$(mktemp -d "${TMPDIR:-/tmp}/exits-selftest.XXXXXX")"
	ok=0
	fail=0
	bump() { if [ "$1" -eq 0 ]; then ok=$((ok + 1)); else fail=$((fail + 1)); fi; }

	# 1. standalone arithmetic command -> fail
	mkdir -p "$TD/case1"
	printf '#!/usr/bin/env bash\nset -e\nx=0\n((x++))\necho survived\n' >"$TD/case1/bad.sh"
	scan "$TD/case1" >/dev/null 2>&1
	[ $? -ne 0 ]
	bump $?

	# 2. function tail -> fail
	mkdir -p "$TD/case2"
	printf '#!/usr/bin/env bash\nset -euo pipefail\nPASS=0\nlog_pass() { echo ok; ((PASS++)); }\n' >"$TD/case2/bad.sh"
	scan "$TD/case2" >/dev/null 2>&1
	[ $? -ne 0 ]
	bump $?

	# 3. assignment form -> pass
	mkdir -p "$TD/case3"
	printf '#!/usr/bin/env bash\nset -e\nx=0\nx=$((x + 1))\necho survived\n' >"$TD/case3/good.sh"
	scan "$TD/case3" >/dev/null 2>&1
	bump $?

	# 4. no errexit -> out of scope, pass
	mkdir -p "$TD/case4"
	printf '#!/usr/bin/env bash\nx=0\n((x++))\necho ok\n' >"$TD/case4/loose.sh"
	scan "$TD/case4" >/dev/null 2>&1
	bump $?

	echo "self-test: $ok ok, $fail failed"
	[ "$fail" -eq 0 ]
	exit $?
fi

echo "── shell exit-status scan: $ROOT ──"
scan "$ROOT" && echo "✅ no arithmetic-statement exit hazards"
