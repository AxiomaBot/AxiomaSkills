---
description: Build one planned chunk unattended — implement its chunk file with tests, self-review, verify, hand off, open the PR and review it
argument-hint: <feature> <chunk>
---

# Build a chunk

**Tier:** coding (floor sonnet). The chunk file ends with a `Build model:`
line — stop if this session is below **that** model (or the floor); never
switch the session down. Runs with auto-accept: no user in the loop, every
decision was settled in the chunk file.

## Gate

1. The chunk file `docs/features/<feature>/chunks/<n>-*.md` exists — else
   stop: run the `plan` skill for `<feature> <chunk>` first.
2. It has no `[?]` marker, its Invariants section is populated or literally
   `None — <why>`, and it carries a `Build model:` line. Otherwise stop and say
   what is missing; the `plan` skill resolves it, not you.
3. The worktree is clean. On `main`, branch first:
   `git checkout -b feat/<feature>-<n>-<slug> origin/main`.

## Read

The chunk file; `AGENTS.md` (code quality bar, domain rules for code
review); `ARCHITECTURE.md` (or this project's equivalent);
`docs/weak-spots.md`. The lint, format and test commands are `CLAUDE.md` →
Commands — use those, never a remembered variant.

## Build

- Implement the tasks in order. Each lands with its own test coverage.
- **Satisfy every invariant before a task is done.** For each one, write the
  test that attacks it — the unauthorised caller, the cross-boundary read,
  the reused token, the forced failure — not a happy-path test that happens
  to pass near it. A literal `None — <why>` has nothing to attack.
- Shared/core services are sacred: run the full suite after touching them.
- Stay inside the chunk's scope. A bug, cleanup or test gap you find that is
  not in the plan is appended to `docs/deferred.md` as an Actionable entry
  (its format is in the file's header) — never chased.
- A deferred entry the chunk file pulled in is closed in place when its task
  lands: `- **Resolved:** <feature>/<n> — <what closed it>`, per the format in
  `docs/deferred.md`'s header. **Leave the PR number out.** The header shows
  it because a fix landing on an open PR has one; you do not, since you write
  this before the PR exists, and filling it in afterwards would leave an
  uncommitted edit sitting on top of a pushed, already-reviewed head. The
  feature and chunk identify the change.
- Run the lint, format and test commands before declaring any task done.

## Self-review

The reviewers on the PR are not the first reviewer — you are.

1. Run `/code-review --high` (a harness skill, not part of this plugin) on
   the diff; address its findings; re-run until clean.
2. Check the diff against every row of `docs/weak-spots.md` whose class it
   touches, and against the domain rules in `AGENTS.md`.
3. Every invariant has its adversarial test; every claim a comment or
   docstring makes about other code is one you opened and confirmed.

## Verify

Green tests are not proof the flow works. Exercise the behaviour the chunk
file's Test strategy → Verify line names, end to end: use this project's own
`verify` skill if it has one, or run the app and drive the path by hand in a
project that has none. Fix what only surfaces at runtime now. Skip only when
the chunk has no runtime surface.

## Finish

1. Commit (conventional commits; `CLAUDE.md` → Commit conventions).
2. Run the `handoff` skill for `<feature> <chunk>` — it folds the Manual test
   steps into the feature checklist, ticks the boxes and sets the status.
   Commit its edits.
3. Push and open the chunk as its own small, non-draft PR into `main` — small
   enough for one complete review. Body: what it does, the chunk it lands,
   the invariants it satisfies.
4. Run the `pr-review` skill.
5. Report: what was built, tests, the `/code-review` outcome, the verify
   result, deferred entries added or closed, both verdicts, and the next
   step — a blocking verdict, a `## Needs broader manual review` item, or a
   security-relevant non-blocking finding → the `fix-review` skill, push,
   `pr-review` again; anything else is a **stop**: squash-merge once CI is
   green, no voluntary pushes.

When spawned by the `auto-chunk` skill, stop after **Verify** and the commit:
the orchestrator owns the handoff, the PR and the review loop.
