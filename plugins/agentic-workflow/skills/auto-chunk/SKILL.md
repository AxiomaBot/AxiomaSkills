---
description: Run one chunk end to end unattended — plan → build → handoff → PR → review loop → squash-merge. You only initialize and manual-test.
argument-hint: <feature> <chunk>
---

# Auto-chunk — one chunk, start to merge

**Tier:** coding (floor sonnet). You are a pure orchestrator: the skills do
the work, you sequence them and apply the gates. Every spawned agent gets its
tier's model explicitly (`CLAUDE.md` → Models) — the planner on the planning
recommendation, the builder on the chunk file's `Build model:`, the fixer on
the fix-review recommendation; the `pr-review` skill passes the reviewers
theirs. Never rely on a sub-skill to switch models.

Target: `$ARGUMENTS` as `<feature> <chunk>`. Empty → ask and stop.

## Guardrails

- **Three terminal states at every stage — proceed, fix, or escalate.**
  Never grind, never merge over a real-looking blocker.
- **A review that failed to run is not a verdict.** After the `pr-review`
  skill's one re-spawn, escalate; never substitute your own review (you hold
  the builder's context) and never re-push to retry.
- **One push per review round.** Fix every blocking issue, verify, push once,
  re-review.
- **Merge to `main` only; never tag.** Releases are the human's.
- **Never commit a permission grant** to any tracked `.claude/settings*.json`
  to get a tool this run needs; an ungranted tool is unavailable.
- Stop the moment the human says so.

## Steps

0. **Set up, or resume.** **On both paths the worktree must be clean**
   (`git status --porcelain` — anything → escalate, never stash or discard):
   unattended, a dirty tree is uncommitted work, or a crashed run's
   leftovers, that must not ride into a fix or handoff commit. The state file
   is `$(git rev-parse --git-dir)/auto_chunk_state.md`, inside the git
   directory and never in the worktree: nothing in this plugin writes a
   consuming project's `.gitignore`, so a state file at the repo root would
   be untracked, show as `??`, and fail that clean-tree check on every single
   resume. Resolve it with `git rev-parse` rather than hardcoding `.git/`,
   which is a file and not a directory in a linked worktree. If it exists,
   this is a resume: check the tree, read the PR, branch and chunk from the
   file, check out that branch, check the tree again, and jump to the
   matching step. Otherwise: `git fetch origin main`;
   `git checkout -b feat/<feature>-<n>-<slug> origin/main` with plain `-b`,
   never `-B`; a name collision → pick another or escalate.
1. **Plan.** Spawn a foreground subagent on the planning model: *run the
   `plan` skill in `--auto` mode for `<feature> <chunk>`; report the
   assumptions recorded, the `Build model:` and any `Review model:` line, and
   any `[?]` verbatim.* A `[?]` → **escalate**: a product decision with no
   safe default is what the human is still for.
2. **Build.** Spawn a foreground subagent on the `Build model:`: *run the
   `build` skill for `<feature> <chunk>`; stop after Verify and the commit —
   the orchestrator owns the rest.* Tests that cannot pass, or a task blocked
   outside the plan → **escalate**.
3. **Handoff.** Run the `handoff` skill yourself; stage its three files by
   name, never `git add -A` — this commit carries bookkeeping only, and a
   blanket add sweeps in whatever else the build left behind; commit.
4. **Open the PR.** Push; open a small, non-draft PR into `main`. Write
   the state file (PR number, branch, chunk, feature) — **this is the
   first point a run is resumable**, so a crash before it leaves a branch and
   no state file, and re-invoking hits step 0's name-collision rule and
   escalates. That is the intended outcome, not a gap: there is no PR yet to
   resume into, and the half-built branch is the human's to inspect. Then
   `subscribe_pr_activity` for out-of-band wakeups — a human comment, a CI
   failure — if it is available; the loop below does not depend on it.
5. **Review loop.** Run the `pr-review` skill (with the chunk file's `Review
   model:` if it has one). Classify:
   - **Clean** — no blocking issue, security PASS, no unresolved truncation
     marker, and every security-relevant finding **drained**
     (`fix-review` skill, step 1), all for this head → step 6.
   - **Blocker, or anything security-relevant and not yet drained** — a
     blocking issue, a security FAIL, a `## Needs broader manual review`
     item, or a security-relevant non-blocking finding (`fix-review` skill,
     step 4 defines the class). Spawn a foreground subagent on the
     fix-review model: *run the `fix-review` skill; both reports are on the
     PR for head `<sha>`.* Verify, commit, push once, back to `pr-review`.
     It is what verifies, files or escalates the security-relevant ones, so
     never route past it to step 6 on the strength of "no blocking issues".
     Equally, a finding it already drained on an earlier head is **not** a
     reason to spawn it again — the reviewers restate those every round, and
     re-spawning on one is the loop that ends at the round guard below
     rather than at a merge.
   - **Disputed or infrastructure** — a blocker the fixer disagrees with on
     evidence that would be re-raised every round, a review that did not run,
     CI failing for a reason outside the diff → **escalate** with the evidence
     and a merge recommendation.
   - About five rounds without converging, or the same subsystem producing
     each round's blocker → **escalate** with where you are stuck.
6. **Merge.** CI green on the current head, both verdicts clean for that
   same SHA, and no security "needs broader manual review" item left
   unverified. If CI is still running, arm `send_later` when available;
   otherwise tell the human it is clean and awaiting CI and stop — never ask
   them to merge in your place. Squash-merge. Never tag.
7. **Finish.** `unsubscribe_pr_activity`; delete the state file. One
   message: the chunk is merged; which boxes are ticked and which not, and
   why; the feature status now; what to manual-test at the named checkpoint
   and that signing it off, marking the feature `done` and tagging are theirs;
   the plan assumptions worth a glance; anything escalated along the way.

## Escalation

When you stop for the human, say, in this order: the **stage** (plan / build /
review-loop / merge); **why**; **what you need** (a decision, an ops action, a
review); the **PR state** — number, branch, CI and review status, and
whether it is safe to merge as-is. Then stop; push nothing further until they
respond.
