#!/usr/bin/env bash
# ============================================================================
# validate-coverage-floors.sh — a coverage floor may not be lowered (ADR-010)
# ============================================================================
# `.pi/coverage-floors.tsv` is a ratchet: raise a floor when a layer improves,
# never lower one to make a build pass. A rule that only lives in prose is not
# a control, so this script makes it executable.
#
# Two failure modes, both named:
#
#   1. a floor DECREASED relative to the base ref — the ratchet moved backwards
#      and the layer's real coverage is now unguarded below where it had reached;
#   2. a layer DISAPPEARED — a removed row stops gating, and a missing row reads
#      as "no floor" rather than "this layer lost its floor".
#
# Table (tab-separated): layer<TAB>floor<TAB>measured<TAB>target<TAB>note
#   floor     the value that gates (ratchet; never decreases)
#   measured  last measured line/region coverage (informational)
#   target    the criterion from the roadmap (gap printed when unmet)
#
# Usage:
#   bash .pi/scripts/validate-coverage-floors.sh              # vs the base ref
#   bash .pi/scripts/validate-coverage-floors.sh --base main
#   bash .pi/scripts/validate-coverage-floors.sh --self-test
# ============================================================================
set -uo pipefail

# Resolve the project root: the nearest ancestor of this script that looks like
# a project (has .git, package.json, or .pi). The `.pi` marker matters in a
# worktree/monorepo layout where the app lives in a subdirectory: git's toplevel
# is not the project root, but `.pi/scripts` always sits below it.
resolve_root() {
	local d
	d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
	while [ "$d" != "/" ]; do
		if [ -e "$d/.git" ] || [ -e "$d/package.json" ] || [ -d "$d/.pi" ]; then
			echo "$d"
			return
		fi
		d="$(dirname "$d")"
	done
	echo "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
}
ROOT="$(resolve_root)"
TABLE_REL=".pi/coverage-floors.tsv"
TABLE="$ROOT/$TABLE_REL"
BASE=""
MODE="check"

while [ $# -gt 0 ]; do
	case "$1" in
	--base) BASE="${2:-}"; shift 2 ;;
	--self-test) MODE="self-test"; shift ;;
	--base-file) MODE="base-file"; BASE="${2:-}"; shift 2 ;;
	--new-file) NEWFILE="${2:-}"; shift 2 ;;
	*) shift ;;
	esac
done

compare() {
	# $1 = base table file, $2 = new table file
	python3 - "$1" "$2" <<'PY'
import sys

def parse(path):
    rows = {}
    for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2:
            print(f"{path}:{lineno}: malformed row (need layer<TAB>floor...)", file=sys.stderr)
            sys.exit(2)
        layer, floor = parts[0], parts[1]
        # An uncommented header row is the column name, not a floor.
        if layer.strip().lower() == "layer":
            continue
        try:
            rows[layer] = float(floor)
        except ValueError:
            print(f"{path}:{lineno}: floor is not a number: {floor!r}", file=sys.stderr)
            sys.exit(2)
    return rows

base = parse(sys.argv[1])
new = parse(sys.argv[2])
problems = []

for layer, b in sorted(base.items()):
    if layer not in new:
        problems.append(f"layer '{layer}' disappeared — its floor ({b:g}) no longer gates")
    elif new[layer] < b - 1e-9:
        problems.append(f"layer '{layer}' floor decreased {b:g} -> {new[layer]:g} "
                        f"(a floor is a ratchet; never lower it)")

if problems:
    print("coverage floors regressed:", file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    sys.exit(1)

raised = [f"{l} {base[l]:g}->{new[l]:g}" for l in base if l in new and new[l] > base[l] + 1e-9]
print(f"coverage floors OK — {len(new)} layer(s), no floor lowered"
      + (f"; raised: {', '.join(raised)}" if raised else ""))
PY
}

if [ "$MODE" = "--self-test" ] || [ "$MODE" = "self-test" ]; then
	TD="$(mktemp -d "${TMPDIR:-/tmp}/floors-selftest.XXXXXX")"
	ok=0
	fail=0
	bump() { if [ "$1" -eq 0 ]; then ok=$((ok + 1)); else fail=$((fail + 1)); fi; }

	tbl() { printf 'layer\tfloor\tmeasured\ttarget\n%s\n' "$2" >"$TD/$1.tsv"; }

	# 1. unchanged -> pass
	tbl base 'domain	90	92	95'
	tbl same 'domain	90	92	95'
	compare "$TD/base.tsv" "$TD/same.tsv" >/dev/null 2>&1
	bump $?

	# 2. raised -> pass
	tbl raised 'domain	95	96	95'
	compare "$TD/base.tsv" "$TD/raised.tsv" >/dev/null 2>&1
	bump $?

	# 3. lowered -> fail
	tbl lowered 'domain	80	92	95'
	compare "$TD/base.tsv" "$TD/lowered.tsv" >/dev/null 2>&1
	[ $? -ne 0 ]
	bump $?

	# 4. layer removed -> fail
	tbl removed 'application	90	91	90'
	compare "$TD/base.tsv" "$TD/removed.tsv" >/dev/null 2>&1
	[ $? -ne 0 ]
	bump $?

	echo "self-test: $ok ok, $fail failed"
	[ "$fail" -eq 0 ]
	exit $?
fi

if [ "$MODE" != "--self-test" ] && [ "$MODE" != "self-test" ] && [ ! -f "$TABLE" ]; then
	echo "no coverage floors table ($TABLE_REL) — nothing to ratchet (OK)"
	exit 0
fi

if [ -n "$BASE" ]; then
	git rev-parse --verify --quiet "$BASE" >/dev/null || {
		echo "unknown base ref: $BASE" >&2
		exit 2
	}
	BASE_COPY="$(mktemp "${TMPDIR:-/tmp}/floors-base.XXXXXX")"
	if ! git show "$BASE:$TABLE_REL" >"$BASE_COPY" 2>/dev/null; then
		echo "no $TABLE_REL at $BASE — first ratchet commit (OK)"
		exit 0
	fi
	compare "$BASE_COPY" "$TABLE"
else
	# Default: compare against the merge base with the default branch when known.
	DEFAULT_BRANCH="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
	[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH="main"
	MB="$(git merge-base HEAD "origin/$DEFAULT_BRANCH" 2>/dev/null || git merge-base HEAD "$DEFAULT_BRANCH" 2>/dev/null || true)"
	if [ -z "$MB" ]; then
		echo "no base commit available — floors unchanged in this checkout (OK)"
		exit 0
	fi
	BASE_COPY="$(mktemp "${TMPDIR:-/tmp}/floors-base.XXXXXX")"
	if ! git show "$MB:$TABLE_REL" >"$BASE_COPY" 2>/dev/null; then
		echo "no $TABLE_REL at merge base — first ratchet commit (OK)"
		exit 0
	fi
	compare "$BASE_COPY" "$TABLE"
fi
