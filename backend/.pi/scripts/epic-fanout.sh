#!/usr/bin/env bash
# ============================================================================
# epic-fanout.sh — start several module epics at once, fully prepared
# ============================================================================
# One call does everything needed for parallel epics:
#
#   1. resolve the modules   (--modules a,b  OR  roadmap order)
#   2. check dependencies    (refuse if a dep is not implemented)
#   3. freezes the contracts (registry: contractFrozen=true)
#   4. create worktree+branch per module (epic/<module>)
#   5. spawn one headless pi agent per worktree, logging to
#      .git/guardian/logs/<module>.log
#
# Usage:
#   epic-fanout.sh [--modules a,b,c] [--tdd] [--max N]
#                  [--spawn] [--dry-run] [--assume-frozen] [--local]
#                  [--base main] [--timeout-ms N]
#
# SAFETY: nothing is spawned without --spawn. The default prepares worktrees
# and prints the exact commands, so you can inspect before any agent runs.
# Contracts must ALREADY be frozen in the registry; this script never freezes
# on your behalf (that made the gate meaningless and started agents on
# unreviewed contracts).
#
# Exit: 0 started/prepared · 2 blocked by a dependency · 1 error
# ============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODULES_RAW=""
TDD=0
MAX=0
FORCE_FREEZE=0
DRY_RUN=0
NO_SPAWN=0
SPAWN=0
ALLOW_REMOTE=0
STOP=0
BASE="main"
TIMEOUT_MS=0

while [ $# -gt 0 ]; do
	case "$1" in
	--modules) MODULES_RAW="${2:-}"; shift 2 ;;
	--tdd) TDD=1; shift ;;
	--max) MAX="${2:-0}"; shift 2 ;;
	--force-freeze) FORCE_FREEZE=1; shift ;;
	--dry-run) DRY_RUN=1; shift ;;
	--no-spawn) NO_SPAWN=1; shift ;;
	--spawn) SPAWN=1; shift ;;
	--assume-frozen)
		echo "⛔ --assume-frozen no longer exists: there is no bypass for the freeze gate." >&2
		echo "   Freeze the module properly:  /architect --freeze --module <m>" >&2
		exit 2
		;;
	--stop) STOP=1; shift ;;
	--allow-remote-issues) ALLOW_REMOTE=1; shift ;;
	--base) BASE="${2:-main}"; shift 2 ;;
	--timeout-ms) TIMEOUT_MS="${2:-0}"; shift 2 ;;
	-h | --help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
	*) echo "unknown argument: $1" >&2; exit 1 ;;
	esac
done

COMMON="$(git rev-parse --git-common-dir 2>/dev/null || echo ".git")"
[ -d "$COMMON" ] || COMMON=".git"
COMMON_ABS="$(cd "$COMMON" 2>/dev/null && pwd || echo "$COMMON")"
LOGDIR="$COMMON_ABS/guardian/logs"
REGISTRY="$ROOT/.pi/scripts/epic-registry.sh"
PARALLEL="$ROOT/.pi/scripts/epic-parallel.sh"
RUNNER="$ROOT/.pi/scripts/epic-runner.mjs"

[ -f "$REGISTRY" ] || { echo "missing $REGISTRY — run guardian update" >&2; exit 1; }
[ -f "$PARALLEL" ] || { echo "missing $PARALLEL — run guardian update" >&2; exit 1; }
[ -f "$RUNNER" ] || { echo "missing $RUNNER — run guardian update" >&2; exit 1; }

# The runner is a Node script; bun also executes it.
# The project directory is the one that owns .pi/ (this script lives in
# <project>/.pi/scripts). It is NOT necessarily the git top level: a monorepo
# often keeps the app in <repo>/backend with .pi/ inside it. Agents must run in
# the project dir, otherwise pi finds no extensions and /architect is not a
# command at all.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GIT_TOP="$(git -C "$PROJECT_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$PROJECT_DIR")"
PROJECT_REL="${PROJECT_DIR#"$GIT_TOP"}"
PROJECT_REL="${PROJECT_REL#/}"

NODE_BIN="$(command -v node || command -v bun || true)"
if [ -z "$NODE_BIN" ]; then
	echo "neither node nor bun found — required to spawn headless agents" >&2
	exit 1
fi

# ── Stop: kill every spawned agent recorded in the registry ─────────────────
if [ "$STOP" -eq 1 ]; then
	PIDS="$(python3 - "$COMMON_ABS/guardian/epics.json" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit
for mod, e in (d.get("epics") or {}).items():
    if isinstance(e, dict) and e.get("pid"):
        print(f"{e['pid']} {mod}")
PY
)"
	if [ -z "$PIDS" ]; then
		echo "No agents recorded in the registry — nothing to stop."
		exit 0
	fi
	echo "Stopping spawned agents:"
	while read -r pid mod; do
		[ -z "$pid" ] && continue
		if kill "$pid" 2>/dev/null; then
			echo "  stopped $mod (pid $pid)"
			bash "$REGISTRY" set "$mod" "status=stopped" "pid=" >/dev/null 2>&1
		else
			echo "  $mod (pid $pid) not running"
			bash "$REGISTRY" set "$mod" "status=stopped" "pid=" >/dev/null 2>&1
		fi
	done <<<"$PIDS"
	echo ""
	echo "Note: each agent's own pi child is terminated with its runner."
	exit 0
fi

# ── Resolve the module list ─────────────────────────────────────────────────
# Explicit list wins. Otherwise take roadmap order, skipping implemented modules.
SELECTED="$(
	python3 - "$ROOT" "$MODULES_RAW" "$MAX" <<'PY'
import os, re, sys

root, raw, max_n = sys.argv[1], sys.argv[2], int(sys.argv[3] or 0)
mods_dir = os.path.join(root, ".pi/architecture/modules")
roadmap = os.path.join(root, ".pi/architecture/implementation-roadmap.md")

def is_implemented(doc_slug):
    for cand in (f"{doc_slug}.md",):
        p = os.path.join(mods_dir, cand)
        if not os.path.exists(p):
            continue
        text = open(p, encoding="utf-8", errors="ignore").read()
        m = re.search(r"\*\*Status:\*\*\s*([A-Za-z ]+)", text)
        if m and m.group(1).strip().lower().startswith(("implemented", "done", "complete")):
            return True
        if len(re.findall(r"status:\s*implemented", text, re.I)) > 0:
            return True
    return False

def slugify(name):
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

if raw.strip():
    items = [m.strip() for m in raw.split(",") if m.strip()]
    print("\n".join(items))
    sys.exit(0)

if not os.path.exists(roadmap):
    print("__ERROR__no roadmap at .pi/architecture/implementation-roadmap.md", file=sys.stderr)
    sys.exit(3)

# Walk phases in order; collect modules from each '### Modules' table.
order, phase = [], None
in_modules = False
for line in open(roadmap, encoding="utf-8", errors="ignore"):
    stripped = line.strip()
    if stripped.startswith("## "):
        phase = stripped[3:].strip()
        in_modules = False
        continue
    if stripped.startswith("### "):
        in_modules = stripped[4:].strip().lower().startswith("modules")
        continue
    if not in_modules or not stripped.startswith("|"):
        continue
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    if len(cells) < 3:
        continue
    BT = chr(96)
    name = cells[0].replace(BT, "").strip()
    if not name or name.lower() in ("module", "modules") or set(name) <= set("-: "):
        continue
    if phase and phase.lower().startswith("phase 0"):
        continue
    doc = cells[-1].replace(BT, "").strip()
    slug = os.path.basename(doc)[:-3] if doc.endswith(".md") else slugify(name)
    order.append((phase or "", name, slug))

selected, seen = [], set()
for ph, name, slug in order:
    if slug in seen:
        continue
    seen.add(slug)
    if is_implemented(slug):
        continue
    selected.append(slug)
    if max_n and len(selected) >= max_n:
        break

print("\n".join(selected))
PY
)"

if printf '%s' "$SELECTED" | grep -q "^__ERROR__"; then
	echo "${SELECTED#__ERROR__}" >&2
	exit 1
fi
if [ -z "$SELECTED" ]; then
	echo "Nothing to start: no planned modules found (roadmap order, implemented skipped)."
	echo "  pass --modules a,b to name them explicitly"
	exit 0
fi

MODULES=()
while IFS= read -r modline; do
	[ -n "$modline" ] && MODULES+=("$modline")
done <<<"$SELECTED"

# ── Batch-size guard ────────────────────────────────────────────────────────
# An unbounded automated batch is how six agents started at once. Spawning
# requires an explicit bound: --max N, or an explicit --modules list of <= 3.
if [ "$SPAWN" -eq 1 ] && [ "$MAX" -le 0 ]; then
	COUNT=${#MODULES[@]}
	if [ "$COUNT" -gt 3 ]; then
		echo "⛔ Refusing to spawn ${COUNT} agents unbounded." >&2
		echo "   Add --max N (recommended 1-3) or pass an explicit --modules list of at most 3." >&2
		echo "   Nothing was created." >&2
		exit 1
	fi
fi

# ── Freeze gate (spec v1): Phase B only runs FROZEN modules ──────────────────
# A module is frozen when freeze.sh verify passes: contracts merged, signatures
# present, behaviour tests RED for the right reason, ACs referenced, deps frozen.
# There is no bypass: this is the one decision a human makes.
FREEZE_SH="$ROOT/.pi/scripts/freeze.sh"
if [ ! -f "$FREEZE_SH" ]; then
	echo "⛔ missing .pi/scripts/freeze.sh — run guardian update" >&2
	exit 1
fi

UNFROZEN=""
for m in ${MODULES[@]+"${MODULES[@]}"}; do
	if ! bash "$FREEZE_SH" verify --module "$m" >/tmp/guardian-freeze-$$.log 2>&1; then
		UNFROZEN="$UNFROZEN$m
"
	fi
done

if [ -n "$UNFROZEN" ]; then
	echo "⛔ Not frozen — Phase B only runs frozen modules:"
	printf '%s' "$UNFROZEN" | sed 's/^/   - /'
	echo ""
	echo "   Freeze first (one module at a time, in dependency order):"
	echo "     /architect --freeze --module <m>"
	echo "   then merge the contract-freeze PR and record it:"
	echo "     bash .pi/scripts/freeze.sh record --module <m> --commit <sha>"
	echo ""
	echo "   Detail for the first module:"
	bash "$FREEZE_SH" verify --module "$(printf '%s' "$UNFROZEN" | head -1)"
	exit 2
fi
rm -f /tmp/guardian-freeze-$$.log

# ── Pre-flight: the spawned agents inherit THIS project's .pi/ ──────────────
# Without extensions, /architect is not a command: the prompt falls through to
# the model, which then improvises (expensive and wrong). Fail before spawning.
if [ "$NO_SPAWN" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
	if [ ! -d "$PROJECT_DIR/.pi/extensions" ]; then
		echo "⛔ $PROJECT_DIR/.pi/extensions is missing — the agent would have no /architect command." >&2
		echo "   Run guardian update in $PROJECT_DIR, or use --no-spawn." >&2
		exit 1
	fi
fi

echo "============================================"
echo "  Parallel epic fan-out"
echo "============================================"
echo "  modules:  ${MODULES[*]:-}"
echo "  tdd:      $([ "$TDD" -eq 1 ] && echo enabled || echo disabled)"
echo "  base:     $BASE"
[ "$DRY_RUN" -eq 1 ] && echo "  mode:     DRY RUN (nothing is created)"
echo ""

# ── Dependency gate ─────────────────────────────────────────────────────────
# A module may only run in parallel once the modules it depends on are
# implemented. Deps inside this same batch cannot be satisfied yet either.
DEP_CHECK="$(python3 - "$ROOT" "$COMMON_ABS/guardian/epics.json" ${MODULES[@]+"${MODULES[@]}"} <<'PY'
import os, re, sys

root = sys.argv[1]
registry_path = sys.argv[2]
batch = sys.argv[3:]
mods_dir = os.path.join(root, ".pi/architecture/modules")


def doc_path(slug):
    p = os.path.join(mods_dir, f"{slug}.md")
    return p if os.path.exists(p) else None

def status_of(slug):
    p = doc_path(slug)
    if not p:
        return "unknown"
    text = open(p, encoding="utf-8", errors="ignore").read()
    m = re.search(r"\*\*Status:\*\*\s*([A-Za-z ]+)", text)
    if m:
        s = m.group(1).strip().lower()
        if s.startswith(("implemented", "done", "complete")):
            return "implemented"
        if s.startswith(("partial", "in progress", "wip")):
            return "partial"
        return "planned"
    if re.search(r"status:\s*implemented", text, re.I):
        return "implemented"
    return "planned"

def deps_of(slug):
    """Modules this one depends on.

    Module docs use several shapes, all of which appear in real projects:
        **Depends On:** none.
        **Depends On:** Alpha, Beta
        ### Depends On
        | Module | What it provides |
        | **Mandate** | ... |

    Critically, a doc may also carry a "Used By" table listing its CONSUMERS.
    Those must never be read as dependencies (that would invert the graph and
    block a module on the work that depends on it).
    """
    p = doc_path(slug)
    if not p:
        return []
    lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()

    # Scope: the "## Dependencies" section if present, else the whole doc.
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

    # Inside that scope, take only the "Depends On" sub-block.
    block, in_deps = [], False
    for ln in scope:
        label = ln.strip()
        heading = re.match(r"^#{2,4}\s*Depends On\b(.*)$", label, re.I)
        bold = re.match(r"^\*\*Depends On:?\*\*(.*)$", label, re.I)
        if heading or bold:
            in_deps = True
            rest = (heading.group(1) if heading else bold.group(1)).strip()
            if rest:
                block.append(rest)
            continue
        if in_deps and re.match(r"^#{2,4}\s", label):
            in_deps = False  # next sibling section, e.g. "### Used By"
            continue
        if in_deps:
            block.append(label)

    if not block:
        return []

    # An explicit "none" anywhere in the Depends On block means: no dependencies.
    joined = " ".join(block)
    if re.search(r"\bnone\b", joined, re.I):
        return []

    found = []
    for ln in block:
        if not ln:
            continue
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if not cells:
                continue
            name = cells[0].replace(chr(96), "").replace("*", "").strip()
            if not name or name.lower() in ("module", "modules") or set(name) <= set("-: "):
                continue
            found.append(name)
        elif ln.startswith("- "):
            name = ln[2:].split("\u2014")[0].split(":")[0].strip().strip(chr(96) + "* ")
            if name and name.lower() != "none":
                found.append(name)
        else:
            # inline list: "Alpha, Beta"
            for part in re.split(r"[,;]", ln):
                nm = part.strip().strip(chr(96) + "* ").rstrip(".")
                if nm and not nm.lower().startswith("none") and len(nm) < 60:
                    found.append(nm)
    return found


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

# Registry state: which modules have frozen contracts. Freeze is the gate for
# parallel work ("merge the contract-freeze issue first"), implementation the
# stricter also-accepted case. Loaded here because it needs slugify().
frozen = set()
try:
    import json
    _reg = json.load(open(registry_path, encoding="utf-8"))
    for _mod, _entry in (_reg.get("epics") or {}).items():
        if isinstance(_entry, dict) and _entry.get("contractFrozen"):
            frozen.add(slugify(_mod))
except Exception:
    frozen = set()

problems = []
for idx, slug in enumerate(batch):
    for dep_name in deps_of(slug):
        dep = slugify(dep_name)
        st = status_of(dep)
        if st == "implemented":
            continue
        if dep in frozen:
            continue
        if dep in batch and batch.index(dep) < idx:
            continue  # frozen earlier in this very run
        if dep in batch:
            problems.append(
                f"{slug}: depends on '{dep_name}', which comes later in this batch — "
                f"reorder so it starts first")
        elif st == "unknown":
            problems.append(
                f"{slug}: depends on '{dep_name}' with no module doc under "
                f".pi/architecture/modules/")
        else:
            problems.append(
                f"{slug}: depends on '{dep_name}' ({st}) and its contracts are not "
                f"frozen — merge its contract-freeze issue, then: "
                f"bash .pi/scripts/epic-registry.sh freeze \"{dep_name}\" --frozen")

if problems:
    print("\n".join(problems))
    sys.exit(1)
sys.exit(0)
PY
)"
DEP_RC=$?

if [ "$DEP_RC" -ne 0 ]; then
	echo "⛔ Blocked — dependencies are not satisfied:"
	echo "$DEP_CHECK" | sed 's/^/   /'
	echo ""
	if [ "$FORCE_FREEZE" -ne 1 ]; then
		echo "   Parallel epics must not build on unfolded contracts."
		echo "   Finish the dependency first, or re-run with --force-freeze to override."
		exit 2
	fi
	echo "   --force-freeze given — continuing anyway (recorded in the registry)."
	echo ""
fi

if [ "$DRY_RUN" -eq 1 ]; then
	echo "Contract freeze status (a real run refuses unfrozen modules):"
	for m in ${MODULES[@]+"${MODULES[@]}"}; do
		slug="$(echo "$m" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
		st="$(python3 - "$COMMON_ABS/guardian/epics.json" "$slug" <<'PY' 2>/dev/null
import json, re, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    print("no"); raise SystemExit
want = sys.argv[2]
for mod, e in (d.get("epics") or {}).items():
    if isinstance(e, dict) and re.sub(r"[^a-z0-9]+", "-", mod.lower()).strip("-") == want:
        print("yes" if e.get("contractFrozen") else "no"); raise SystemExit
print("no")
PY
)"
		[ "$st" = "yes" ] && echo "  ✓ $m" || echo "  ✗ $m  (not frozen)"
	done
	echo ""
	echo "Would do, per module:"
	for m in ${MODULES[@]+"${MODULES[@]}"}; do
		slug="$(echo "$m" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
		echo "  • freeze   $m"
		echo "  • worktree ../$(basename "$ROOT")-$slug   (branch epic/$slug)"
		[ "$NO_SPAWN" -eq 0 ] && echo "  • spawn    pi (rpc) → log .git/guardian/logs/$slug.log"
	done
	exit 0
fi

# ── Freeze, create worktrees, spawn ─────────────────────────────────────────
mkdir -p "$LOGDIR"
STARTED=()
FAILED=()

for m in ${MODULES[@]+"${MODULES[@]}"}; do
	slug="$(echo "$m" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
	log="$LOGDIR/$slug.log"

	echo "────────────────────────────────────────────"
	echo "▶ $m"


	# 2. worktree + epic branch (gated on the freeze we just recorded)
	WT_OUT="$(bash "$PARALLEL" "$m" --base "$BASE" 2>&1)"
	WT_RC=$?
	if [ "$WT_RC" -ne 0 ]; then
		echo "  ✗ worktree failed (exit $WT_RC)"
		echo "$WT_OUT" | sed 's/^/    /'
		FAILED+=("$m")
		continue
	fi
	WT="$(echo "$WT_OUT" | sed -n 's/.*worktree: *//p' | head -1)"
	if [ -z "$WT" ] || [ ! -d "$WT" ]; then
		# epic-parallel prints the path; fall back to the conventional name
		WT="$(dirname "$ROOT")/$(basename "$ROOT")-$slug"
	fi
	echo "  ✓ worktree $WT"

	if [ "$SPAWN" -eq 0 ] || [ "$NO_SPAWN" -eq 1 ]; then
		echo "  → run:  cd \"$WT${PROJECT_REL:+/$PROJECT_REL}\" && /architect --epic \"$m\"$( [ "$TDD" -eq 1 ] && echo " --tdd")"
		STARTED+=("$m")
		continue
	fi

	# 3. spawn one headless agent in the worktree (RPC mode dispatches the command)
	#    cwd must be the PROJECT dir inside the worktree (where .pi/ lives).
	SPAWN_CWD="$WT"
	[ -n "$PROJECT_REL" ] && SPAWN_CWD="$WT/$PROJECT_REL"
	if [ ! -d "$SPAWN_CWD/.pi/extensions" ]; then
		echo "  ✗ $SPAWN_CWD/.pi/extensions missing — refusing to spawn a blind agent"
		FAILED+=("$m")
		continue
	fi
	# GUARDIAN_LOCAL_ONLY keeps the spawned epic from creating remote issues
	# unless the caller explicitly allowed it (--allow-remote-issues).
	export GUARDIAN_LOCAL_ONLY="$([ "$ALLOW_REMOTE" -eq 1 ] && echo 0 || echo 1)"
	"$NODE_BIN" "$RUNNER" \
		"/architect --epic \"$m\"$( [ "$TDD" -eq 1 ] && echo " --tdd")" \
		--cwd "$SPAWN_CWD" --log "$log" ${TIMEOUT_MS:+--timeout-ms "$TIMEOUT_MS"} \
		>/dev/null 2>&1 &
	PID=$!
	bash "$REGISTRY" set "$m" "pid=$PID" "log=$log" "spawnedAt=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1
	echo "  ✓ spawned pid $PID → $log"
	STARTED+=("$m")
done

echo "────────────────────────────────────────────"
echo ""
echo "Started ${#STARTED[@]}/${#MODULES[@]} epic(s)."
[ "${#FAILED[@]}" -gt 0 ] && echo "Failed: ${FAILED[*]:-}"
if [ "$SPAWN" -eq 0 ] || [ "$NO_SPAWN" -eq 1 ]; then
	echo ""
	echo "Nothing was spawned (default). Worktrees are ready and empty."
	echo "Re-run with --spawn to launch agents, or run the commands above yourself."
fi

if [ "${#STARTED[@]}" -gt 0 ] && [ "$SPAWN" -eq 1 ] && [ "$NO_SPAWN" -eq 0 ]; then
	echo ""
	echo "Monitor:"
	echo "  bash .pi/scripts/epic-registry.sh list"
	for m in ${STARTED[@]+"${STARTED[@]}"}; do
		slug="$(echo "$m" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
		echo "  tail -f \"$LOGDIR/$slug.log\""
	done
fi
[ "${#FAILED[@]}" -gt 0 ] && exit 1
exit 0