# Epic Scale-out — start parallel epics (one worktree per module)

<!--
Canonical Reference: .pi/prompts/epic-parallel.md
Implements: parallel epics (/architect --parallel / --worktree and /epic)
-->

**Purpose:** Run several module epics at the same time without them colliding on
shared contracts. One module → one epic branch → one worktree → one PR.

---

## Preconditions

1. **Contracts frozen.** The module's shared contracts (ports, DTOs, error envelope,
   composition-root seam) are merged to the base branch. Parallel epics must never
   redefine shared contracts — that is what produces merge conflicts and rework.
2. Clean base: `git status` clean, `main` up to date.

---

## Procedure (per module, can be repeated in parallel)

```bash
# 1. Record the contract freeze (done once, after the freeze issue merges)
bash .pi/scripts/epic-registry.sh freeze "<Module>" --frozen

# 2. Create the worktree + epic branch (blocked with exit 2 if not frozen)
bash .pi/scripts/epic-parallel.sh "<Module>"

# 3. In the new worktree, start the epic (epic mode: one branch, one PR)
cd ../<repo>-<module>
/architect --epic "<Module>"
```

Repeat steps 2–3 for each additional module — the worktrees are isolated, so the
epics run concurrently. Each epic still commits only to its own `epic/<module>`
branch and opens exactly one PR at the end (epic mode).

---

## Rules

- **Never** start two epics for the same module in parallel.
- **Never** bypass the freeze gate; if it blocks, run the Contract Freeze issue first.
- Register/new worktrees are visible across all worktrees via the shared registry
  (`.git/guardian/epics.json`):

```bash
bash .pi/scripts/epic-registry.sh list
```

- Merge order: freeze branches first, then epics in dependency order (see the
  roadmap `### Dependencies`). An epic whose dependency is not merged must wait.
