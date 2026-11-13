#!/usr/bin/env bash
# ============================================================================
# validate-guards.sh — make gating vs advisory explicit (ADR-010)
# ============================================================================
# A validator that cannot fail is documentation, not a control. This is the one
# place that answers "which checks can stop a merge?".
#
#   * every root .pi/scripts/validate-*.sh MUST be registered in .pi/guards.tsv
#   * every row must be well-formed and point at a file that exists
#   * a duplicate or phantom registration is rejected
#
# Usage:
#   bash .pi/scripts/validate-guards.sh              # registry integrity (advisory)
#   bash .pi/scripts/validate-guards.sh --list       # print the classified table
#   bash .pi/scripts/validate-guards.sh --run        # run the gating set (run_here=yes)
#   bash .pi/scripts/validate-guards.sh --self-test  # prove the check bites
# ============================================================================
set -uo pipefail

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
ROOT="$(resolve_root)"
REG="$ROOT/.pi/guards.tsv"

MODE="${1:-check}"

# --self-test must work in any checkout (it builds its own throwaway roots), so
# the registry requirement applies to the real check only.
if [ "$MODE" != "--self-test" ] && [ ! -f "$REG" ]; then
	echo "guard registry missing: .pi/guards.tsv" >&2
	echo "  run: guardian update --force  (recreates project-owned template files)" >&2
	exit 2
fi

registry_check() {
	# $1 = registry path, $2 = root, $3 = mode (check|list)
	python3 - "$1" "$2" "$3" <<'PY'
import os, re, sys

reg, root, mode = sys.argv[1:4]
rows, seen, errors = [], set(), []

for lineno, line in enumerate(open(reg, encoding="utf-8"), 1):
    if line.startswith("#") or not line.strip():
        continue
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 6:
        errors.append(f"{lineno}: malformed row (need 6 tab-separated fields)")
        continue
    guard, cls, tier, run_here, owner, notes = parts[:6]
    if tier not in ("gating", "advisory"):
        errors.append(f"{lineno}: bad tier {tier!r} (want gating|advisory)")
    if run_here not in ("yes", "no"):
        errors.append(f"{lineno}: bad run_here {run_here!r} (want yes|no)")
    if not os.path.exists(os.path.join(root, guard)):
        errors.append(f"{lineno}: registered guard does not exist: {guard}")
    if guard in seen:
        errors.append(f"{lineno}: duplicate registration: {guard}")
    seen.add(guard)
    rows.append((guard, cls, tier, run_here, owner, notes))

scripts_dir = os.path.join(root, ".pi/scripts")
on_disk = sorted(
    f".pi/scripts/{n}"
    for n in (os.listdir(scripts_dir) if os.path.isdir(scripts_dir) else [])
    if re.fullmatch(r"validate-.*\.sh", n)
)
unregistered = [p for p in on_disk if p not in seen]

if errors:
    print("guard registry invalid — .pi/guards.tsv:", file=sys.stderr)
    for e in errors:
        print(f"    {e}", file=sys.stderr)
    sys.exit(2)

if unregistered:
    print("unclassified guard(s) — add them to .pi/guards.tsv:", file=sys.stderr)
    for p in unregistered:
        print(f"    {p}", file=sys.stderr)
    print("  every guard declares gating|advisory, run_here and an owner.", file=sys.stderr)
    sys.exit(2)

if mode == "list":
    gating = [r for r in rows if r[2] == "gating"]
    advisory = [r for r in rows if r[2] == "advisory"]
    print("GATING (a non-zero exit fails a mandatory path):")
    for g, c, _t, run_here, o, _n in gating:
        where = "run here" if run_here == "yes" else "gates elsewhere"
        print(f"  {c:<18} {g:<48} [{where}]  owner={o}")
    print("\nADVISORY (informational; does not stop a merge):")
    for g, c, _t, _r, o, _n in advisory:
        print(f"  {c:<18} {g:<48}  owner={o}")
    print(f"\n{len(on_disk)} validator script(s) on disk, all classified "
          f"({len(gating)} gating, {len(advisory)} advisory).")
    sys.exit(0)

print(f"guard registry OK — {len(on_disk)} validator(s), all classified "
      f"({sum(1 for r in rows if r[2]=='gating')} gating).")
PY
}

case "$MODE" in
--self-test)
	# Prove the checks bite, in throwaway roots under a temp dir.
	TD="$(mktemp -d "${TMPDIR:-/tmp}/guards-selftest.XXXXXX")"
	ok=0
	fail=0
	bump() { if [ "$1" -eq 0 ]; then ok=$((ok + 1)); else fail=$((fail + 1)); fi; }

	# 1. a guard on disk that is not registered must be rejected
	mkdir -p "$TD/case1/.pi/scripts"
	printf '#!/usr/bin/env bash\nexit 0\n' >"$TD/case1/.pi/scripts/validate-planted.sh"
	{ echo "# g\tclass\ttier\trun_here\towner\tnotes"; } >"$TD/case1/.pi/guards.tsv"
	registry_check "$TD/case1/.pi/guards.tsv" "$TD/case1" check >/dev/null 2>&1
	[ $? -ne 0 ]
	bump $?

	# 2. a bad tier must be rejected
	mkdir -p "$TD/case2/.pi/scripts"
	printf '#!/usr/bin/env bash\nexit 0\n' >"$TD/case2/.pi/scripts/validate-x.sh"
	printf '.pi/scripts/validate-x.sh\tclass\twrong-tier\tno\towner\tnote\n' >"$TD/case2/.pi/guards.tsv"
	out2="$(registry_check "$TD/case2/.pi/guards.tsv" "$TD/case2" check 2>&1)"
	case "$out2" in *"bad tier"*) bump 0 ;; *) bump 1 ;; esac

	# 3. a fully classified registry must pass
	mkdir -p "$TD/case3/.pi/scripts"
	printf '#!/usr/bin/env bash\nexit 0\n' >"$TD/case3/.pi/scripts/validate-y.sh"
	printf '.pi/scripts/validate-y.sh\tclass\tgating\tyes\towner\tnote\n' >"$TD/case3/.pi/guards.tsv"
	registry_check "$TD/case3/.pi/guards.tsv" "$TD/case3" check >/dev/null 2>&1
	bump $?

	echo "self-test: $ok ok, $fail failed"
	[ "$fail" -eq 0 ]
	;;
--run)
	registry_check "$REG" "$ROOT" check || exit 1
	echo "── gating guards ──"
	rc=0
	while IFS=$'\t' read -r guard _cls tier run_here _owner _notes; do
		case "$guard" in \#* | "") continue ;; esac
		if [ "$tier" = "gating" ] && [ "$run_here" = "yes" ]; then
			echo "▶ $guard"
			if ! bash "$ROOT/$guard"; then
				rc=1
				echo "✗ $guard FAILED"
			fi
		fi
	done <"$REG"
	[ "$rc" -eq 0 ] && echo "✅ all gating guards passed"
	exit "$rc"
	;;
--list)
	registry_check "$REG" "$ROOT" list
	;;
*)
	registry_check "$REG" "$ROOT" check
	;;
esac
