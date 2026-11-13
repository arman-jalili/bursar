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
#                  [--force-freeze] [--dry-run] [--no-spawn]
#                  [--base main] [--timeout-ms N]
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
NODE_BIN="$(command -v node || command -v bun || true)"
if [ -z "$NODE_BIN" ]; then
	echo "neither node nor bun found — required to spawn headless agents" >&2
	exit 1
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

# A dependency is satisfied when it is IMPLEMENTED or its CONTRACTS ARE FROZEN.
# Freeze is the gate for parallel work — that is what "merge the contract freeze
# issue first" means in practice. Implementation is the stricter, also-accepted
# case. A dependency earlier in this same batch is frozen before the dependent
# starts (fan-out freezes in order), so it counts as frozen.
frozen = set()
try:
    import json
    reg = json.load(open(registry_path, encoding="utf-8"))
    for mod, entry in (reg.get("epics") or {}).items():
        if entry.get("contractFrozen"):
            frozen.add(slugify(mod))
except Exception:
    pass

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

	# 1. record the contract freeze (the gate below requires it)
	bash "$REGISTRY" freeze "$m" --frozen >/dev/null 2>&1

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

	if [ "$NO_SPAWN" -eq 1 ]; then
		echo "  → run:  cd \"$WT\" && /architect --epic \"$m\"$( [ "$TDD" -eq 1 ] && echo " --tdd")"
		STARTED+=("$m")
		continue
	fi

	# 3. spawn one headless agent in the worktree (RPC mode dispatches the command)
	"$NODE_BIN" "$RUNNER" \
		"/architect --epic \"$m\"$( [ "$TDD" -eq 1 ] && echo " --tdd")" \
		--cwd "$WT" --log "$log" ${TIMEOUT_MS:+--timeout-ms "$TIMEOUT_MS"} \
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

if [ "${#STARTED[@]}" -gt 0 ]; then
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