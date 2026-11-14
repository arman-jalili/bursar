#!/usr/bin/env bash
# ============================================================================
# validate-wiring-claims.sh — keep "it is wired" claims honest (ADR-009)
# ============================================================================
# The repeating failure this guards: code that exists, compiles, passes its own
# tests, and is never reached — while the module doc says it is wired. Grep
# finds the symbol; only a checked claim answers the question, and a one-off
# audit is true for exactly one commit.
#
# The manifest `.pi/architecture/wiring-claims.tsv` is that audit in
# machine-readable form:
#
#   claim<TAB>module<TAB>status<TAB>evidence<TAB>note
#
#   status = CONFIRMED  the wiring exists; `evidence` (a path or path:symbol)
#                       must still be found — fails when it disappears.
#   status = GAP        the wiring is missing and the doc must say so; fails
#                       when callers/evidence appear (promote the row) or when
#                       the module doc stops declaring the gap.
#
# Both directions matter: docs drift back into claiming wiring after it was
# known missing, and gaps get silently closed without the doc being updated.
#
# Usage:
#   bash .pi/scripts/validate-wiring-claims.sh             # check (gating)
#   bash .pi/scripts/validate-wiring-claims.sh --list      # print the table
#   bash .pi/scripts/validate-wiring-claims.sh --self-test
#   bash .pi/scripts/validate-wiring-claims.sh --claims F --root D
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
CLAIMS="$ROOT/.pi/architecture/wiring-claims.tsv"
MODE="check"

while [ $# -gt 0 ]; do
	case "$1" in
	--self-test) MODE="self-test"; shift ;;
	--list) MODE="list"; shift ;;
	--claims) CLAIMS="${2:-}"; shift 2 ;;
	--root) ROOT="${2:-}"; shift 2 ;;
	-h | --help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
	*)
		echo "unknown argument: $1" >&2
		exit 2
		;;
	esac
done

claims_check() {
	# $1 = root, $2 = claims file, $3 = mode
	# (--self-test plants its own manifest, so no project table is required)
	python3 - "$1" "$2" "$3" <<'PY'
import os, sys

root, claims_path, mode = sys.argv[1:4]

if not os.path.exists(claims_path) and mode != "selftest":
    print(f"missing wiring-claims manifest: {claims_path}", file=sys.stderr)
    print("  create .pi/architecture/wiring-claims.tsv "
          "(header comments + claim<TAB>module<TAB>status<TAB>evidence<TAB>note)",
          file=sys.stderr)
    sys.exit(2)

rows, errors = [], []
for lineno, line in enumerate(open(claims_path, encoding="utf-8"), 1):
    if line.startswith("#") or not line.strip():
        continue
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 4:
        errors.append(f"{lineno}: malformed row (need claim<TAB>module<TAB>status<TAB>evidence[<TAB>note])")
        continue
    claim, module, status, evidence = parts[:4]
    note = parts[4] if len(parts) > 4 else ""
    # A leading/uncommented header row is the column name, not a claim.
    if (claim, module, status) == ("claim", "module", "status"):
        continue
    if status not in ("CONFIRMED", "GAP"):
        errors.append(f"{lineno}: bad status {status!r} (want CONFIRMED|GAP)")
        continue
    rows.append((claim, module, status, evidence, note, lineno))

def evidence_found(ev):
    """Evidence is `path` or `path:symbol`; both halves must resolve."""
    path, _, symbol = ev.partition(":")
    full = os.path.join(root, path)
    if not os.path.exists(full):
        return False
    if not symbol:
        return True
    if os.path.isdir(full):
        for dp, _dn, fs in os.walk(full):
            for f in fs:
                try:
                    if symbol in open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read():
                        return True
                except OSError:
                    pass
        return False
    try:
        return symbol in open(full, encoding="utf-8", errors="ignore").read()
    except OSError:
        return False

def doc_declares_gap(module):
    """A GAP row requires the module doc to still declare the gap."""
    for cand in (
        os.path.join(root, ".pi/architecture/modules", f"{module}.md"),
        os.path.join(root, ".pi/architecture/modules", f"{module.replace('_','-')}.md"),
    ):
        if os.path.exists(cand):
            text = open(cand, encoding="utf-8", errors="ignore").read().lower()
            return any(k in text for k in ("not wired", "wiring gap", "no runtime integration", "bootstrap only"))
    return False

if mode == "list":
    fmt = "{:<34} {:<26} {:<10} {}"
    print(fmt.format("claim", "module", "status", "evidence"))
    for claim, module, status, evidence, _n, _l in rows:
        print(fmt.format(claim, module, status, evidence))
    print(f"\n{len(rows)} claim(s).")
    sys.exit(0)

if errors:
    print("wiring-claims manifest invalid:", file=sys.stderr)
    for e in errors:
        print(f"    {e}", file=sys.stderr)
    sys.exit(2)

problems = []
for claim, module, status, evidence, _note, lineno in rows:
    found = evidence_found(evidence)
    if status == "CONFIRMED" and not found:
        problems.append(
            f"{lineno}: CONFIRMED claim '{claim}' has no evidence — "
            f"'{evidence}' disappeared while the claim stands "
            f"(module {module})")
    elif status == "GAP":
        if found:
            problems.append(
                f"{lineno}: GAP claim '{claim}' now has evidence — "
                f"'{evidence}' exists, promote the row to CONFIRMED")
        elif not doc_declares_gap(module):
            problems.append(
                f"{lineno}: GAP claim '{claim}' is not declared in the module doc — "
                f".pi/architecture/modules/{module}.md must state the gap")

if problems:
    print(f"wiring claims: {len(rows)} row(s), {len(problems)} unresolved:", file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    print("\n  CONFIRMED rows need live evidence; GAP rows need the gap documented "
          "and must be promoted once the wiring lands.", file=sys.stderr)
    sys.exit(1)

print(f"wiring claims OK — {len(rows)} row(s): "
      f"{sum(1 for r in rows if r[2]=='CONFIRMED')} confirmed, "
      f"{sum(1 for r in rows if r[2]=='GAP')} documented gap(s).")
PY
}

case "$MODE" in
--self-test | self-test)
	TD="$(mktemp -d "${TMPDIR:-/tmp}/claims-selftest.XXXXXX")"
	ok=0
	fail=0
	bump() { # $1 = exit status, $2 = label
		if [ "$1" -eq 0 ]; then ok=$((ok + 1)); else fail=$((fail + 1)); echo "  x case $2" >&2; fi
	}
	mk() { mkdir -p "$TD/$1/.pi/architecture/modules" "$TD/$1/src"; }

	mk c1
	printf 'def handler(): pass\n' >"$TD/c1/src/app.py"

	# 1. CONFIRMED with live evidence -> pass
	printf 'claim\tmodule\tstatus\tevidence\nh1\tm1\tCONFIRMED\tsrc/app.py:handler\n' >"$TD/c1/claims.tsv"
	claims_check "$TD/c1" "$TD/c1/claims.tsv" selftest >/dev/null 2>&1
	bump $? 1

	# 2. CONFIRMED whose evidence vanished -> fail
	printf 'claim\tmodule\tstatus\tevidence\nh1\tm1\tCONFIRMED\tsrc/app.py:gone_symbol\n' >"$TD/c1/claims.tsv"
	claims_check "$TD/c1" "$TD/c1/claims.tsv" selftest >/dev/null 2>&1
	[ $? -ne 0 ]
	bump $? 2

	# 3. GAP with callers present -> fail (must be promoted)
	printf 'claim\tmodule\tstatus\tevidence\nh1\tm1\tGAP\tsrc/app.py:handler\n' >"$TD/c1/claims.tsv"
	claims_check "$TD/c1" "$TD/c1/claims.tsv" selftest >/dev/null 2>&1
	[ $? -ne 0 ]
	bump $? 3

	# 4. GAP declared in the module doc, still unwired -> pass
	printf 'claim\tmodule\tstatus\tevidence\nh1\tm1\tGAP\tsrc/nowhere.py\n' >"$TD/c1/claims.tsv"
	printf '# m1\n\nThis module is not wired by design.\n' >"$TD/c1/.pi/architecture/modules/m1.md"
	claims_check "$TD/c1" "$TD/c1/claims.tsv" selftest >/dev/null 2>&1
	bump $? 4

	# 5. bad status rejected (exit 2)
	printf 'claim\tmodule\tstatus\tevidence\nh1\tm1\tMAYBE\tsrc/x\n' >"$TD/c1/claims.tsv"
	claims_check "$TD/c1" "$TD/c1/claims.tsv" selftest >/dev/null 2>&1
	[ $? -eq 2 ]
	bump $? 5

	echo "self-test: $ok ok, $fail failed"
	[ "$fail" -eq 0 ]
	;;
--list | list)
	claims_check "$ROOT" "$CLAIMS" list
	;;
*)
	claims_check "$ROOT" "$CLAIMS" check
	;;
esac
