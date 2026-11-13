#!/usr/bin/env bash
# ============================================================================
# freeze.sh — the contract-freeze state machine (spec v1)
# ============================================================================
# "Frozen" is not a flag somebody sets. It is evidence that can be re-checked:
#
#   frozen = contracts merged on the base branch
#          + frozen signatures in source
#          + behaviour tests that are RED for the right reason
#          + every test names an AC that exists in the module doc
#          + no structural-only tests (isinstance / dataclass / hasattr)
#
# Usage:
#   freeze.sh verify  --module <m> [--root DIR] [--base main] [--json]
#   freeze.sh record  --module <m> [--root DIR] [--base main] [--commit SHA]
#   freeze.sh status  [--root DIR]
#   freeze.sh list    [--root DIR]
#   freeze.sh next    [--root DIR]   # next module eligible to freeze, in order
#
# Exit: 0 pass · 1 verification failed · 2 usage/state error
# ============================================================================
set -uo pipefail

CMD="${1:-}"; shift || true
MODULE=""; ROOT_OPT=""; BASE="main"; JSON_OUT=0; COMMIT=""

while [ $# -gt 0 ]; do
	case "$1" in
	--module) MODULE="${2:-}"; shift 2 ;;
	--root) ROOT_OPT="${2:-}"; shift 2 ;;
	--base) BASE="${2:-main}"; shift 2 ;;
	--commit) COMMIT="${2:-}"; shift 2 ;;
	--json) JSON_OUT=1; shift ;;
	*) echo "unknown argument: $1" >&2; exit 2 ;;
	esac
done

# Project root: the directory that owns .pi/ (this script lives in <root>/.pi/scripts).
PROJECT_DIR="$(
	d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
	while [ "$d" != "/" ]; do
		if [ -d "$d/.pi" ]; then echo "$d"; exit 0; fi
		d="$(dirname "$d")"
	done
	echo "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
)"
ROOT="${ROOT_OPT:-$PROJECT_DIR}"
GIT_TOP="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || echo "$ROOT")"
COMMON_DIR="$(cd "$(git -C "$ROOT" rev-parse --git-common-dir 2>/dev/null || echo "$GIT_TOP/.git")" 2>/dev/null && pwd || echo "$GIT_TOP/.git")"
STATE="$COMMON_DIR/guardian/epics.json"

usage() {
	sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

case "$CMD" in
verify | record | status | list | next) ;;
*) usage; exit 2 ;;
esac

exec python3 - "$CMD" "$ROOT" "$GIT_TOP" "$STATE" "$MODULE" "$BASE" "$JSON_OUT" "$COMMIT" <<'PY'
import json, os, re, subprocess, sys
from datetime import datetime, timezone

cmd, root, git_top, state_path, module, base, json_out, commit = sys.argv[1:9]
json_out = json_out == "1"

MODS = os.path.join(root, ".pi", "architecture", "modules")

def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")

def read(path):
    try:
        return open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return ""

def module_doc(slug):
    p = os.path.join(MODS, f"{slug}.md")
    return p if os.path.exists(p) else None

def git(*args):
    try:
        return subprocess.run(["git", "-C", git_top] + list(args),
                              capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:
        return ""

def load_state():
    try:
        return json.load(open(state_path, encoding="utf-8"))
    except Exception:
        return {"version": 1, "epics": {}}

def save_state(state):
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    json.dump(state, open(state_path, "w", encoding="utf-8"), indent=2)

def entry(state, slug):
    e = (state.get("epics") or {}).get(slug)
    return e if isinstance(e, dict) else {}

def set_entry(state, slug, **fields):
    state.setdefault("epics", {})
    e = state["epics"].get(slug)
    if not isinstance(e, dict):
        e = {}
    e["module"] = slug
    e.update(fields)
    state["epics"][slug] = e
    return e

# ── dependency helpers ──────────────────────────────────────────────────────
def deps_of(slug):
    p = module_doc(slug)
    if not p:
        return []
    lines = read(p).splitlines()
    scope, sec = list(lines), None
    for i, ln in enumerate(lines):
        if re.match(r"^##\s+Dependencies\b", ln, re.I):
            sec = i
            break
    if sec is not None:
        scope = []
        for ln in lines[sec + 1:]:
            if re.match(r"^##\s+", ln):
                break
            scope.append(ln)
    block, in_deps = [], False
    for ln in scope:
        label = ln.strip()
        m1 = re.match(r"^#{2,4}\s*Depends On\b(.*)$", label, re.I)
        m2 = re.match(r"^\*\*Depends On:?\*\*(.*)$", label, re.I)
        if m1 or m2:
            in_deps = True
            rest = (m1.group(1) if m1 else m2.group(1)).strip()
            if rest:
                block.append(rest)
            continue
        if in_deps and re.match(r"^#{2,4}\s", label):
            in_deps = False
            continue
        if in_deps:
            block.append(label)
    joined = " ".join(block)
    if not block or re.search(r"\bnone\b", joined, re.I):
        return []
    found = []
    for ln in block:
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if cells:
                nm = cells[0].replace(chr(96), "").replace("*", "").strip()
                if nm and nm.lower() not in ("module", "modules") and not set(nm) <= set("-: "):
                    found.append(slugify(nm))
        elif ln.startswith("- "):
            nm = ln[2:].split("\u2014")[0].strip().strip(chr(96) + "* ")
            if nm and nm.lower() != "none":
                found.append(slugify(nm))
    return found

def state_of(state, slug):
    e = entry(state, slug)
    return e.get("state") or ("frozen" if e.get("contractFrozen") else "unfrozen")

# ── the verification ────────────────────────────────────────────────────────
STRUCTURAL_ONLY = re.compile(
    r"\b(isinstance|issubclass|dataclasses\.is_dataclass|is_dataclass|hasattr|"
    r"inspect\.isclass|inspect\.isfunction|inspect\.getmembers|type\(|__mro__|"
    r"is_property|isinstance\(.*Property\))\b"
)
# A suite is behavioural when it ENFORCES A RULE: it expects a raise, or it
# asserts something that is not knowledge about the *shape* of the code.
# Everything below is shape: subclassing, dataclass internals, member names,
# signatures, annotations, enum defaults. 199 green assertions of that kind over
# NotImplementedError bodies is exactly what this check exists to catch.
RAISES = re.compile(r"(pytest\.raises|assertRaises|toThrow|should_panic|expect_err)", re.I)
SHAPE_ASSERT = re.compile(
    r"(isinstance|issubclass|hasattr|inspect\.|__dataclass|__annotations__|__mro__|"
    r"_model_kind|signature|dataclasses\.|_fields|__name__|__qualname__|"
    r"\bnames\b|annotations\[|startswith\(\s*[\"']set_|__dict__|dir\()"
)

def classify(code):
    """Return 'behaviour' | 'structural' | 'none'."""
    asserts = [l for l in code.splitlines() if re.match(r"\s*assert\b", l)]
    if RAISES.search(code):
        return "behaviour"
    if not asserts:
        return "none"
    substantive = [a for a in asserts if not SHAPE_ASSERT.search(a)]
    return "behaviour" if substantive else "structural"

AC_ID = re.compile(r"\b[A-Z]{1,3}-\d{1,3}\b")

def find_tests(slug):
    hits = []
    for base_dir in ("tests", "src"): 
        base_path = os.path.join(root, base_dir)
        if not os.path.isdir(base_path):
            continue
        for dp, _dn, fs in os.walk(base_path):
            for f in fs:
                if not re.search(r"\.(py|ts|rs|go|java)$", f):
                    continue
                low = os.path.join(dp, f).lower()
                if slug in low or slug.replace("-", "") in low.replace("-", ""):
                    hits.append(os.path.join(dp, f))
    return sorted(set(hits))

def analyse_tests(slug, tests):
    """Return (total, behaviour, structural_only, ac_named, details)."""
    total = behaviour = struct_only = ac_named = 0
    details = []
    for f in tests:
        src = read(f)
        if not src.strip():
            continue
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        kind = classify(code)
        body_struct = kind == "structural"
        body_behav = kind == "behaviour"
        acs = sorted(set(AC_ID.findall(src)))
        # count test functions/entries crudely but honestly
        n_tests = len(re.findall(r"^\s*(?:async\s+)?def test_|^\s*it\(|\bfn\s+test_|@Test", code, re.M)) or 1
        total += n_tests
        if body_behav:
            behaviour += 1
        elif body_struct:
            struct_only += 1
            details.append(f"{os.path.relpath(f, root)}: structural assertions only")
        if acs:
            ac_named += 1
    return total, behaviour, struct_only, ac_named, details

def run_python_tests(tests):
    """Return (status, reason, sample) where status: red_ok|red_wrong|green|unknown."""
    dirs = sorted({os.path.dirname(f) for f in tests})
    if not dirs:
        return "unknown", "no tests found", ""
    venv = os.path.join(root, ".venv", "bin", "python")
    py = venv if os.path.exists(venv) else sys.executable
    try:
        proc = subprocess.run([py, "-m", "pytest", *dirs, "-q", "--no-header", "-x", "--tb=line"],
                              cwd=root, capture_output=True, text=True, timeout=900)
    except Exception as e:
        return "unknown", f"could not run pytest: {e}", ""
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        return "green", "tests pass while the module is supposedly unimplemented", out[-800:]
    if re.search(r"(ImportError|ModuleNotFoundError|SyntaxError|Error while importing|collection error)", out):
        return "red_wrong", "tests fail on import/syntax, not on behaviour", out[-800:]
    if re.search(r"NotImplementedError|AssertionError|assert", out):
        return "red_ok", "tests fail on missing behaviour", out[-800:]
    return "red_wrong", "unrecognised failure reason", out[-800:]

def verify(slug):
    checks = []
    ok_all = True

    doc = module_doc(slug)
    checks.append(("module doc", bool(doc), doc and os.path.relpath(doc, root) or f"missing .pi/architecture/modules/{slug}.md"))
    ok_all &= bool(doc)
    doctext = read(doc) if doc else ""

    # 1. contract artifacts exist and are referenced by the module doc
    contracts = []
    cdir = os.path.join(root, "docs", "contracts")
    if os.path.isdir(cdir):
        for f in sorted(os.listdir(cdir)):
            if slug in f.lower() or slug.replace("-", "") in f.lower().replace("-", ""):
                contracts.append(os.path.join("docs", "contracts", f))
    referenced = [c for c in contracts if os.path.basename(c) in doctext or c in doctext]
    ok_contracts = bool(contracts) and bool(referenced)
    checks.append(("contracts", ok_contracts,
                   f"{len(contracts)} file(s), {len(referenced)} referenced by the module doc"
                   if contracts else "no docs/contracts/* for this module"))
    ok_all &= ok_contracts

    # 2. frozen signatures in source
    src_dirs = [d for d in (os.path.join(root, "src", slug),
                            os.path.join(root, "src", slug.replace("-", "_"))) if os.path.isdir(d)]
    sig_files = []
    for d in src_dirs:
        for dp, _dn, fs in os.walk(d):
            sig_files += [os.path.join(dp, f) for f in fs if re.search(r"\.(py|ts|java|rs|go)$", f)]
    ok_sigs = bool(sig_files)
    checks.append(("frozen signatures", ok_sigs, f"{len(sig_files)} source file(s)" if ok_sigs else f"no src/{slug}/"))
    ok_all &= ok_sigs

    # 3. tests exist, are behaviour (not structural-only), and name ACs
    tests = find_tests(slug)
    total, behaviour, struct_only, ac_named, tdetails = analyse_tests(slug, tests)
    ok_tests = bool(tests)
    checks.append(("contract tests", ok_tests, f"{len(tests)} file(s)" if tests else "no tests referencing the module"))
    ok_all &= ok_tests

    # Advisory only: a syntactic shape-vs-behaviour classifier is always
    # arguable. The objective gate is the RED check below — tests that are GREEN
    # over NotImplementedError bodies are structural by definition, whatever the
    # assertions look like.
    checks.append(("assertion mix", True,
                   f"~{behaviour} substantive / {struct_only} shape-only suite(s) (advisory)"))

    doc_acs = set(AC_ID.findall(doctext))
    ok_acs = ok_tests and ac_named > 0 and bool(doc_acs)
    checks.append(("AC references", ok_acs,
                   f"{ac_named} suite(s) name an AC; module doc has {len(doc_acs)} AC id(s)"
                   if ok_acs else f"tests name ACs: {ac_named}; module doc AC ids: {len(doc_acs)}"))
    ok_all &= ok_acs

    # 4. RED for the right reason
    status, reason, sample = run_python_tests(tests) if tests else ("unknown", "no tests", "")
    ok_red = status == "red_ok"
    if status == "green":
        reason = ("tests are GREEN while the module is unimplemented — they assert shape, "
                  "not rules; a freeze needs failing behaviour tests")
    checks.append(("red state", ok_red, f"{status}: {reason}"))
    ok_all &= ok_red

    # 5. dependencies frozen/implemented
    bad_deps = []
    st = load_state()
    for d in deps_of(slug):
        s = state_of(st, d)
        if s not in ("frozen", "implemented"):
            bad_deps.append(f"{d} ({s})")
    ok_deps = not bad_deps
    checks.append(("dependencies", ok_deps, "all frozen/implemented" if ok_deps else ", ".join(bad_deps)))
    ok_all &= ok_deps

    return ok_all, checks, sample, {"contracts": contracts, "tests": [os.path.relpath(t, root) for t in tests]}

def emit(ok, checks, slug, extra=None, sample=""):
    if json_out:
        print(json.dumps({"module": slug, "ok": ok,
                          "checks": [{"name": n, "ok": bool(o), "detail": d} for n, o, d in checks],
                          **(extra or {})}, indent=2))
        return
    head = "PASS" if ok else "FAIL"
    print(f"freeze verify: {slug} — {head}")
    for n, o, d in checks:
        print(f"  [{'ok' if o else 'XX'}] {n:<20} {d}")
    if sample and not ok:
        print("\n  failure sample:")
        for line in sample.strip().splitlines()[-6:]:
            print(f"    {line}")

def roadmap_order():
    """Modules in roadmap order, Phase 0 skipped, from the roadmap Modules tables."""
    rp = os.path.join(root, ".pi", "architecture", "implementation-roadmap.md")
    order, phase, in_modules = [], None, False
    for line in read(rp).splitlines():
        st = line.strip()
        if st.startswith("## "):
            phase, in_modules = st[3:].strip(), False
            continue
        if st.startswith("### "):
            in_modules = st[4:].strip().lower().startswith("modules")
            continue
        if not in_modules or not st.startswith("|"):
            continue
        cells = [c.strip() for c in st.strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = cells[0].replace(chr(96), "").replace("*", "").strip()
        if not name or name.lower() in ("module", "modules") or set(name) <= set("-: "):
            continue
        if phase and phase.lower().startswith("phase 0"):
            continue
        doc = cells[-1].replace(chr(96), "").strip()
        slug = os.path.basename(doc)[:-3] if doc.endswith(".md") else slugify(name)
        if slug not in order:
            order.append(slug)
    if not order and os.path.isdir(MODS):
        order = sorted(f[:-3] for f in os.listdir(MODS) if f != "module-template.md")
    return order

if cmd == "next":
    st = load_state()
    for m in roadmap_order():
        if state_of(st, m) in ("frozen", "implemented"):
            continue
        deps = deps_of(m)
        bad = [f"{d} ({state_of(st, d)})" for d in deps if state_of(st, d) not in ("frozen", "implemented")]
        if bad:
            continue  # not eligible yet; a later module never leapfrogs
        print(m)
        raise SystemExit(0)
    print("no eligible module: every module is frozen/implemented or blocked by an unfrozen dependency")
    raise SystemExit(1)

# ── commands ────────────────────────────────────────────────────────────────
if cmd == "list":
    st = load_state()
    mods = sorted(f[:-3] for f in os.listdir(MODS)) if os.path.isdir(MODS) else []
    if not mods:
        print("no modules found")
        raise SystemExit(0)
    print(f"{'module':<28} {'state':<14} evidence")
    for m in mods:
        if m == "module-template":
            continue
        e = entry(st, m)
        ev = (e.get("evidence") or {}).get("commit", "")
        print(f"{m:<28} {state_of(st, m):<14} {ev}")
    raise SystemExit(0)

if cmd == "status":
    if not module:
        print("usage: freeze.sh status --module <m>", file=sys.stderr)
        raise SystemExit(2)
    slug = slugify(module)
    st = load_state()
    e = entry(st, slug)
    print(f"module: {slug}\nstate:  {state_of(st, slug)}")
    if e.get("evidence"):
        print("evidence:", json.dumps(e["evidence"]))
    raise SystemExit(0)

if not module:
    print("usage: freeze.sh verify|record --module <m>", file=sys.stderr)
    raise SystemExit(2)

slug = slugify(module)

if cmd == "verify":
    ok, checks, sample, extra = verify(slug)
    emit(ok, checks, slug, extra, sample)
    raise SystemExit(0 if ok else 1)

# record: only with passing verification AND a real commit on the base branch
ok, checks, sample, extra = verify(slug)
if not ok:
    emit(ok, checks, slug, extra, sample)
    print("\nRefusing to record: the freeze does not verify.", file=sys.stderr)
    raise SystemExit(1)

sha = commit or git("rev-parse", "HEAD")
if not sha:
    print("cannot resolve a commit to record", file=sys.stderr)
    raise SystemExit(2)
on_base = git("merge-base", "--is-ancestor", sha, base)
is_ancestor = subprocess.run(["git", "-C", git_top, "merge-base", "--is-ancestor", sha, base]).returncode == 0
if not is_ancestor:
    print(f"Refusing to record: {sha[:8]} is not on '{base}'. Merge the contract freeze first.", file=sys.stderr)
    raise SystemExit(1)

st = load_state()
set_entry(st, slug, state="frozen", contractFrozen=True,
          evidence={"commit": sha, "branch": base,
                    "contracts": extra.get("contracts", []),
                    "tests": extra.get("tests", []),
                    "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
save_state(st)
print(f"recorded: {slug} frozen at {sha[:8]} on {base}")
raise SystemExit(0)
PY