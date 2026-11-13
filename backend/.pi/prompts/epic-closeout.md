# Epic Closeout — one PR for the whole epic

<!--
Canonical Reference: .pi/prompts/epic-closeout.md
Implements: /architect epic-mode closeout (one branch, one PR, full-epic CI)
-->

**Purpose:** All issues of this epic have been implemented on the shared epic branch.
Open **one** pull request for the epic, let CI validate the **complete** epic, and merge it.
This replaces the per-issue closeout when the pipeline runs in epic mode.

---

## Preconditions

1. Every issue of the epic is implemented and committed on the epic branch.
2. Local CI is green for the full branch:

```bash
bash .pi/scripts/ci/run_preflight.sh
bash .pi/scripts/validate-architecture.sh
bash .pi/scripts/validate-tests.sh
bash .pi/scripts/validate-canonical.sh
```

3. The epic branch is up to date with the base branch (rebase, do not merge the base in).

---

## Open the single epic PR

```bash
# Push the epic branch
git push -u origin <epic-branch>

# One PR for the whole epic (body lists every issue)
gh pr create \
  --base main \
  --head <epic-branch> \
  --title "feat(<module>): <epic name> epic" \
  --body "$(cat <<'EOF'
## Epic
<module> — <epic name>

## Issues
- [ ] #<n> <title>
- [ ] #<n> <title>

## Evidence
- Local CI green on the full epic branch
- Architecture validators green (incl. language consistency)
- Test suite green

Closes #<n>, #<n>
EOF
)"
```

For GitLab use `glab mr create` with the same content (see `.pi/scripts/create-mr.sh`).

---

## Validate, then merge

- Wait for CI **once** — it runs against the full epic, which is a stronger
  signal than N per-issue runs.
- On green: merge (squash or merge-commit per repo policy) and delete the branch.
- Record the epic completion in `.pi/architecture/CHANGELOG.md` and set the module
  doc status to implemented.

---

## Rules

- **Never** open a PR/MR per issue in epic mode.
- **Never** merge before CI reports on the epic PR.
- If a single issue fails after the epic PR is open, fix it on the epic branch and
  push — do not open additional PRs.
