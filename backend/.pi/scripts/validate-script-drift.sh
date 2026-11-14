#!/usr/bin/env bash
# ============================================================================
# validate-script-drift.sh — one source of truth for mirrored .pi/ trees (ADR-010)
# ============================================================================
# `.pi/` is copied into sub-projects / crates, so the same command name can end
# up as a *different program* depending on which tree invoked it. This guard
# fails when a file mirrored across trees differs AND is not a recorded,
# reviewed difference.
#
# Trees are the immediate subdirectories that carry a `.pi` directory, plus the
# repo root. Differences are recorded in `.pi/script-drift-allow.tsv`:
#
#   pattern<TAB>trees<TAB>reason
#
# A pattern present below means the difference is known; the reason says whether
# it is by design, inert, or drift deliberately not reconciled.
#
# Usage:
#   bash .pi/scripts/validate-script-drift.sh            # check (gating)
#   bash .pi/scripts/validate-script-drift.sh --list     # show recorded + drifted
#   bash .pi/scripts/validate-script-drift.sh --self-test
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
ALLOW="$ROOT/.pi/script-drift-allow.tsv"
MODE="${1:-check}"

drift_check() {
	# $1 = root, $2 = allowlist path, $3 = mode, $4... = subtrees ("." is root)
	python3 - "$@" <<'PY'
import fnmatch, hashlib, os, sys

root, allow_path, mode = sys.argv[1:4]
# Each remaining argument is "label=dir"; `dir` contains a scripts/ subtree.
pairs = []
for a in sys.argv[4:]:
    label, _, d = a.partition("=")
    if d:
        pairs.append((label, d))
if not pairs:
    pairs = [(".", os.path.join(root, ".pi"))]

records = []
if os.path.exists(allow_path):
    for lineno, line in enumerate(open(allow_path, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            print(f"{allow_path}:{lineno}: malformed row "
                  f"(need pattern<TAB>trees<TAB>reason)", file=sys.stderr)
            sys.exit(2)
        records.append((parts[0], parts[1], "\t".join(parts[2:])))

def recorded(rel):
    for pat, _trees, reason in records:
        if fnmatch.fnmatch(rel, pat):
            return reason
    return None

contents = {}
for label, d in pairs:
    d = os.path.normpath(os.path.join(d, "scripts"))
    if not os.path.isdir(d):
        continue
    for dirpath, _dirnames, files in os.walk(d):
        for f in files:
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, d)
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            contents.setdefault(rel, {})[label] = h

mirrored = {r: d for r, d in contents.items() if len(d) >= 2}
drifted = {r: d for r, d in mirrored.items() if len(set(d.values())) > 1}
allowed = {r: d for r, d in drifted.items() if recorded(r) is not None}
bad = {r: d for r, d in drifted.items() if recorded(r) is None}

if mode == "list":
    print(f"mirrored files checked: {len(mirrored)}")
    print(f"recorded differences (allowed): {len(allowed)}")
    for r in sorted(allowed):
        print(f"  {r}")
        print(f"      trees: {','.join(sorted(allowed[r]))}")
        print(f"      why:   {recorded(r)}")
    print(f"unrecorded differences: {len(bad)}")
    for r in sorted(bad):
        print(f"  {r}")
        for t in sorted(bad[r]):
            print(f"      {t:<10} {bad[r][t][:16]}")
    sys.exit(0)

if not mirrored:
    print("script drift: nothing mirrored — no trees to compare (OK)")
    sys.exit(0)

print(f"script drift: {len(mirrored)} mirrored files, "
      f"{len(allowed)} recorded difference(s), {len(bad)} unrecorded")

if bad:
    print("", file=sys.stderr)
    print("Unintentional drift — mirrored files differ and are not recorded in "
          ".pi/script-drift-allow.tsv:", file=sys.stderr)
    for r in sorted(bad):
        print(f"  {r}", file=sys.stderr)
        for t in sorted(bad[r]):
            print(f"      {t:<10} {bad[r][t][:16]}", file=sys.stderr)
        print("      -> reconcile to one implementation, or record the "
              "difference with a reason", file=sys.stderr)
    sys.exit(1)

print("OK — every unrecorded mirrored file is byte-identical across trees.")
PY
}

# Trees compared by default:
#   1. the repo root;
#   2. every immediate subdirectory that carries .pi/scripts (crate layout);
#   3. any mirror pair declared in .pi/mirrors.tsv (e.g. templates/pi -> .pi).
# Declaring a mirror is how a framework repo compares its canonical tree with
# the copy it ships in.
# Directories compared. Each entry is a directory that CONTAINS a `scripts/`
# subtree; files are compared by path relative to that `scripts/` dir.
#   * the repo root (.pi/scripts is the root .pi/ -> its scripts dir)
#   * every immediate subdirectory carrying .pi/scripts (crate layout)
#   * any extra tree declared in .pi/mirrors.tsv (one path per line, e.g.
#     templates/pi — how a framework compares its canonical tree with the copy
#     it ships inside the repo).
tree_dirs() {
	echo "$ROOT/.pi"
	for d in "$ROOT"/*/; do
		[ -d "$d.pi/scripts" ] && echo "${d%/}/.pi"
	done
	local mirrors="$ROOT/.pi/mirrors.tsv"
	if [ -f "$mirrors" ]; then
		while IFS= read -r line; do
			case "$line" in \#*|"") continue ;; esac
			line="$(echo "$line" | tr -d '[:space:]')"
			[ -n "$line" ] && [ -d "$ROOT/$line/scripts" ] && echo "$ROOT/$line"
		done <"$mirrors"
	fi
}

# label=dir arguments for the real comparison; label is the display name.
tree_args() {
	local out=""
	for d in $(tree_dirs); do
		local rel="${d#"$ROOT"/}"
		out="$out ${rel}=$d"
	done
	echo "$out"
}

case "$MODE" in
--self-test)
	TD="$(mktemp -d "${TMPDIR:-/tmp}/drift-selftest.XXXXXX")"
	ok=0
	fail=0
	bump() {
		if [ "$1" -eq 0 ]; then ok=$((ok + 1)); else fail=$((fail + 1)); echo "  x case $2" >&2; fi
	}

	# 1. identical copies -> pass
	mkdir -p "$TD/case1/pi/scripts" "$TD/case1/crate/pi/scripts"
	printf 'echo a\n' >"$TD/case1/pi/scripts/tool.sh"
	cp "$TD/case1/pi/scripts/tool.sh" "$TD/case1/crate/pi/scripts/tool.sh"
	: >"$TD/case1/allow.tsv"
	drift_check "$TD/case1" "$TD/case1/allow.tsv" check "pi=$TD/case1/pi" "crate=$TD/case1/crate/pi" >/dev/null 2>&1
	bump $? 1

	# 2. divergent copies, unrecorded -> fail
	mkdir -p "$TD/case2/pi/scripts" "$TD/case2/crate/pi/scripts"
	printf 'echo a\n' >"$TD/case2/pi/scripts/tool.sh"
	printf 'echo b\n' >"$TD/case2/crate/pi/scripts/tool.sh"
	: >"$TD/case2/allow.tsv"
	drift_check "$TD/case2" "$TD/case2/allow.tsv" check "pi=$TD/case2/pi" "crate=$TD/case2/crate/pi" >/dev/null 2>&1
	[ $? -ne 0 ]
	bump $? 2

	# 3. divergent copies, recorded -> pass
	printf 'tool.sh\tpi,crate\tby design\n' >"$TD/case2/allow.tsv"
	drift_check "$TD/case2" "$TD/case2/allow.tsv" check "pi=$TD/case2/pi" "crate=$TD/case2/crate/pi" >/dev/null 2>&1
	bump $? 3

	echo "self-test: $ok ok, $fail failed"
	[ "$fail" -eq 0 ]
	;;
--list | list)
	# shellcheck disable=SC2046
	drift_check "$ROOT" "$ALLOW" list $(tree_args)
	;;
*)
	[ -f "$ALLOW" ] || printf '' >"$ALLOW"
	# shellcheck disable=SC2046
	drift_check "$ROOT" "$ALLOW" check $(tree_args)
	;;
esac
