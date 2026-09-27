---
description: Scaffold or migrate a project into the per-feature workflow layout (init), or verify it (check) — the layout, the AGENTS.md/CLAUDE.md sections, the model floors, and every depends-on entry
argument-hint: init | check
---

# Workflow — scaffold and verify the layout

**Tier:** coding (floor sonnet) — stop if this session is below it; never
switch the session down.

Every other skill reads this layout by path and by heading: `roadmap.md` for
the feature index, `docs/features/<slug>/feature.md` for a feature, its
`chunks/` for build contracts, `docs/weak-spots.md` for the recurring
mistakes, and named sections of `AGENTS.md` and `CLAUDE.md`. `check` verifies
all of that; `init` writes the skeleton `check` expects.

## `check`

Run with the project's own Python (see `CLAUDE.md` → Commands — e.g.
`poetry run python`, `uv run python`, or plain `python3`; the script is
stdlib-only):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/workflow_check.py
```

Exit 0 means every rule held. Otherwise each line is `<file>: <what>` —
quote them verbatim. The script is the contract and its docstring lists every
rule; don't re-derive a rule by reading the files yourself, and a rule that
is wrong is a change to this skill's script, in its own PR.

What a pass does **not** mean: these are checks on the layout and on the
shape of what the files claim, not on the behaviour they describe. A
`dark-ship` line passes when it names a non-UI code reference — not because
anything confirmed that gate exists, is reached on every path, or defaults
off. Read a clean run as "nothing structural is missing", never as evidence
that a control holds.

`check` writes nothing. Fix a finding as an ordinary edit after reporting:
attended, ask which to fix now; unattended, fix only the mechanical ones — a
missing section, a missing `manual_tests.md` — and escalate anything that
needs a decision: a `dark-ship` line, a dependency on a chunk that does not
exist, a feature with a row but no folder, and **a status that disagrees
between `roadmap.md` and `feature.md`**. The check reports that two files
disagree; it cannot tell you which is right, and guessing can quietly reverse
a human's `done`.

## `init`

Attended only: the direction paragraph and the feature list are the user's
judgment. Stop if there is no one to ask. Two starting points, one result:

- **Fresh project** — nothing exists yet. Interview for the project name, the
  direction paragraph, and the features (one line each, with their status:
  `idea`, `outlined`, or — for the one about to start — `outlined` now and
  the `roadmap` skill's `detail` mode next; and the features each cannot
  start before, for its `After` cell).
- **Migration** — a plan exists in another shape (one plan file, one test
  checklist, one deferred log). Read it all first. Then: closed phases become
  one row each under `## Done`; the phase in flight becomes a feature folder
  (the `roadmap` skill's `detail` mode writes the file — run it, or write it
  to its template with the landed chunks ticked); every superseded file moves
  into `docs/archive/` **verbatim** with `git mv`, never edited; the deferred
  log restarts from its open actionable entries only; the recurring-blocker
  list from any build or review prompt seeds `docs/weak-spots.md` one line
  each, anecdotes dropped.

Then, in order:

1. Write `roadmap.md` from `${CLAUDE_PLUGIN_ROOT}/templates/roadmap.md` and
   `docs/weak-spots.md` from `${CLAUDE_PLUGIN_ROOT}/templates/weak-spots.md`;
   create `docs/features/`, `docs/retros/`, `docs/deferred.md` (header:
   *Actionable only* plus the entry format) and `docs/roadmap_changelog.md`.
   Put a `.keep` in each directory you leave empty: git carries files, not
   directories, so without one the directory never reaches the next clone and
   `check` fails for whoever clones next.
2. Add the `AGENTS.md` sections from
   `${CLAUDE_PLUGIN_ROOT}/templates/agents-sections.md` and, in `CLAUDE.md`,
   `## Commands` (lint, format, test, one fenced block — this project's own,
   there is no template for it) and `## Models`, copied verbatim from
   `${CLAUDE_PLUGIN_ROOT}/templates/models.md`. Then tune the *Recommended*
   column and the *Go one up when* triggers to the project — the floors are
   the method, the recommendations are the project's to set.

   That template is the **only** copy of the tier table anywhere in this
   plugin. Read it; never retype it from memory or from the README, which
   deliberately does not reproduce it. Changing a floor is an edit to that
   one file, plus `TIERS` in this skill's own check script when a tier is
   renamed. This plugin's own repo pins the two together in CI, so a missed
   copy fails by name rather than drifting.

3. Install the whole `pr-guards.yml` from
   `${CLAUDE_PLUGIN_ROOT}/templates/pr-guards.yml` to
   `.github/workflows/pr-guards.yml`, and its two scripts from
   `${CLAUDE_PLUGIN_ROOT}/templates/check_committed_permission_grants.py` and
   `${CLAUDE_PLUGIN_ROOT}/templates/check_review_coverage.sh` to
   `scripts/check_committed_permission_grants.py` and
   `scripts/check_review_coverage.sh` (the `.sh` one executable; the guard is
   run as `python3 <path>` and is stdlib-only) — gitleaks on the PR's
   commits, the committed-permission-grant guard, and review coverage. All
   three, not only review coverage — the first two are the deterministic
   floor under everything the agents do. This workflow and these two scripts
   are committed to the project, never regenerated from the plugin at review
   time: GitHub Actions runs against the project's own checkout, not the
   plugin's.
4. Run `check`. `init` is done only when it passes.

### Templates

The feature file and chunk file templates live at
`${CLAUDE_PLUGIN_ROOT}/templates/feature.md` and
`${CLAUDE_PLUGIN_ROOT}/templates/chunk.md`; the `roadmap`, `plan` and
`handoff` skills point here rather than repeating them.

Status values, in order: `idea` → `outlined` → `planned` (folder exists) →
`building` → `built` (all chunks merged, checkpoint pending) → `done`. Rows
at `planned` or later link their folder; earlier rows do not.
