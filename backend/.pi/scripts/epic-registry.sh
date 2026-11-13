#!/usr/bin/env bash
# ============================================================================
# epic-registry.sh — project-level epic registry shared across git worktrees
# ============================================================================
# Worktrees each have their own .pi/ directory, so epic state is invisible
# across parallel /architect sessions. The registry lives in the git COMMON
# dir (shared by all worktrees) and records: module, branch, worktree path,
# status, contract-freeze state and the shared dependencies the module needs.
#
# Run as:
#   epic-registry.sh register <module> [--branch B] [--worktree P] [--status S]
#   epic-registry.sh status <module> <status>
#   epic-registry.sh freeze   <module> [--frozen|--pending]
#   epic-registry.sh list
#   epic-registry.sh get <module>
#   epic-registry.sh path                 # registry file path
# ============================================================================
set -uo pipefail

common_dir() {
	git rev-parse --git-common-dir 2>/dev/null || echo ".git"
}
COMMON="$(common_dir)"
[ -d "$COMMON" ] || COMMON=".git"
# Absolute path: the registry must be addressable from any worktree/cwd.
COMMON_ABS="$(cd "$COMMON" 2>/dev/null && pwd || echo "$COMMON")"
REG="$COMMON_ABS/guardian/epics.json"
mkdir -p "$(dirname "$REG")" 2>/dev/null || true

now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

ensure() {
	[ -f "$REG" ] || echo '{"version":1,"epics":{}}' > "$REG"
}

read_epic() {
	local mod="$1"
	python3 - "$REG" "$mod" <<'PY' 2>/dev/null || echo "{}"
import json,sys
path,mod=sys.argv[1],sys.argv[2]
try:
    d=json.load(open(path))
except Exception:
    d={"version":1,"epics":{}}
print(json.dumps(d.get("epics",{}).get(mod,{})))
PY
}

write_epic() {
	local mod="$1"; shift
	python3 - "$REG" "$mod" "$@" <<'PY'
import json,sys,os
path,mod=sys.argv[1],sys.argv[2]
pairs=sys.argv[3:]
try:
    d=json.load(open(path))
except Exception:
    d={"version":1,"epics":{}}
d.setdefault("epics",{})
e=d["epics"].get(mod,{})
for p in pairs:
    k,_,v=p.partition("=")
    if v in ("true","false"):
        e[k]=v=="true"
    else:
        e[k]=v
e.setdefault("module",mod)
d["epics"][mod]=e
os.makedirs(os.path.dirname(path),exist_ok=True)
json.dump(d,open(path,"w"),indent=2)
print(json.dumps(e))
PY
}

cmd="${1:-}"; shift || true
case "$cmd" in
	path) ensure; echo "$REG" ;;
	register)
		MOD="${1:?usage: register <module> [--branch B] [--worktree P]}"; shift || true
		BRANCH=""; WT=""; STATUS="running"
		while [ $# -gt 0 ]; do
			case "$1" in
				--branch) BRANCH="${2:-}"; shift 2 ;;
				--worktree) WT="${2:-}"; shift 2 ;;
				--status) STATUS="${2:-}"; shift 2 ;;
				*) shift ;;
			esac
		done
		[ -z "$BRANCH" ] && BRANCH="epic/$(echo "$MOD" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
		[ -z "$WT" ] && WT="$(cd "$(dirname "$0")/../.." 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null || pwd)"
		FNOW="$(now)"
		# Preserve an already-frozen contract: re-registering (e.g. a worktree
		# restarted) must never silently un-freeze a module.
		PRESENT=$(read_epic "$MOD")
		KEEP_FROZEN=$(python3 - "$PRESENT" <<'PY' 2>/dev/null || echo ""
import json,sys
try:
    e=json.loads(sys.argv[1])
except Exception:
    e={}
print("true" if e.get("contractFrozen") else "false")
PY
)
		[ -z "$KEEP_FROZEN" ] && KEEP_FROZEN="false"
		write_epic "$MOD" "branch=$BRANCH" "worktree=$WT" "status=$STATUS" "registeredAt=$FNOW" "updatedAt=$FNOW" "contractFrozen=$KEEP_FROZEN" >/dev/null
		echo "registered $MOD -> $BRANCH ($WT)"
		;;
	status)
		MOD="${1:?usage: status <module> <status>}"; ST="${2:?}"
		write_epic "$MOD" "status=$ST" "updatedAt=$(now)" >/dev/null
		echo "$MOD: $ST"
		;;
	freeze)
		MOD="${1:?usage: freeze <module> [--frozen|--pending]}"; shift || true
		V="true"; [ "${1:-}" = "--pending" ] && V="false"
		write_epic "$MOD" "contractFrozen=$V" "updatedAt=$(now)" >/dev/null
		echo "$MOD: contractFrozen=$V"
		;;
	set)
		MOD="${1:?usage: set <module> key=value ...}"; shift || true
		if [ $# -eq 0 ]; then echo "set: need at least one key=value" >&2; exit 1; fi
		write_epic "$MOD" "$@" >/dev/null
		echo "$MOD: $*"
		;;
	list|get)
		MOD="${1:-}"
		ensure
		python3 - "$REG" "$cmd" "$MOD" <<'PY'
import json,sys
path,mode,mod=sys.argv[1],sys.argv[2],sys.argv[3]
d=json.load(open(path))
epics=d.get("epics",{})
if mode=="get":
    print(json.dumps(epics.get(mod,{}),indent=2))
else:
    if not epics: print("(no epics registered)")
    for m,e in sorted(epics.items()):
        print(f"{m:32} {e.get('status','?'):12} frozen={'yes' if e.get('contractFrozen') else 'no ':3} branch={e.get('branch','?')} worktree={e.get('worktree','?')}")
PY
		;;
	*)
		echo "usage: epic-registry.sh register|status|freeze|set|list|get|path ..." >&2
		exit 1 ;;
esac
