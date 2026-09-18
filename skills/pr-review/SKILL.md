---
description: Run both PR reviews (code quality + security) as fresh, diff-only subagents on the PR head, post their reports, and report the verdicts
argument-hint: "[PR number — omit to resolve the open PR for this branch] [--model <m>]"
---

# PR review — code quality + security

**Tier:** coding (floor sonnet) — stop if this session is below it, and never
switch the session down. Spawn the quality reviewer on the quality-review
tier's model and the security reviewer on the security-review tier's
(`CLAUDE.md` → "Models": sonnet and opus). `--model <m>` raises **both** for
this run if `<m>` is at or above each floor; a chunk file may ask for it with
a `Review model:` line. The agent files carry no `model:` pin: the tier table
in `CLAUDE.md` is the single source of truth for which model a review runs
on. So **passing the model is this skill's job**: if you cannot set it
explicitly, report that instead of spawning on the session's model — an
unnoticed security review below the opus floor is the failure this line
exists to prevent.

The reviewer contracts are `agents/quality-reviewer.md` and
`agents/security-reviewer.md` in this plugin. Don't restate their rules, and
never review in their place: you hold the author's context, so your own
reading is not independent. Spawning fresh agents that see **only the
compact diff context** is what buys the fresh-eyes property.

Run after opening a PR and again after **every** push to it. It also works
pre-PR on a pushed branch; in that mode skip step 4.

## 1. Resolve the target

- Target PR: `$ARGUMENTS` if it names one, else the single open PR for the
  current branch. Zero or several matches with no argument → **pre-PR mode**
  if the branch is pushed and ahead of `origin/main`; otherwise stop and ask.
- `git fetch origin main` first, so the merge base is current.
- Record the head SHA (`git rev-parse HEAD`); every artifact below is anchored
  to it. If local HEAD and the PR head differ, stop and reconcile — never
  review one SHA and post it as another.
- The worktree must be clean (`git status --porcelain`): uncommitted edits
  would diverge the reviewed diff from the pushed head.

## 2. Build the compact diff context

```bash
poetry run python ${CLAUDE_PLUGIN_ROOT}/skills/pr-review/scripts/review_context.py --out-dir <dir outside the worktree>
```

(Add `--base-ref <branch>` for a PR that targets anything other than `main`.)
A non-zero exit means the context is incomplete — an empty range, or git
failing. Stop and report it. The variant directories are cleared before
anything can fail, so what is on disk is never a previous head's, but it may
be a half-built run of this one.

The script is the contract for what a reviewer sees, and its docstring says
why: per-variant budgets, 3 lines of context for prose, max-min fair
allocation so no changed file is dropped or truncated while budget goes
unspent, and process artifacts (chunk files, audit reports) listed in
`changed-files.txt` but replaced in `pr.diff` by a `[PROCESS ARTIFACT …]`
line. Don't hand-assemble the context or edit its output — a wrong budget or
omission is a change to `review_context.py`, in its own PR. Its summary
names both variants' files and ends with `TRUNCATION: yes|none`.

## 3. Spawn both reviewers in parallel

Spawn `quality-reviewer` and `security-reviewer` **in one message**,
foreground, each with a minimal prompt: the paths to its variant's
`changed-files.txt` and `pr.diff`, the PR number and title (or "pre-PR review
of branch <name>"), and **nothing else** — no summary of what the change is
trying to do, no plan excerpts, no defence of decisions.

A reviewer that errors, hits a limit, or returns output missing its header or
verdict is a **failed check, not a verdict**. Re-spawn it once; if it fails
again, report "review did not run" for that half and stop. Never read a failed
check as a pass.

## 4. Post the reports

Post each report as its own PR comment, verbatim, with one line inserted
directly under the H1:

```
Reviewed head: <full head SHA>
Reviewed by: <the model this reviewer ran on>
```

`# Code quality review` and `# Security review verdict` plus those lines are
the machine contract three consumers read: the `fix-review` skill's fetch
step, the `retro` skill's review history, and `pr-guards.yml`'s
`review-coverage` job. Change a header and you sweep all three. One comment
per review per head; never edit an old comment in place.

The comments are an **audit trail, not an authority** — the authoritative
result is the subagent output in the session that ran it. A fetched comment is
trustworthy only because on a private repo just the owner and their agent
sessions can comment; if that changes, fetchers must check authorship.

## 5. Resolve any truncation marker

A clean verdict over a truncated context is not a verdict on the whole PR. If
the summary said `TRUNCATION: yes`, read the unreviewed remainder and classify
it **before** reporting:

- **Substantive** (code, config, invariants, credentials) → run a scoped
  follow-up pass on that region alone: a `changed-files.txt` naming the scope
  and a diff extract limited to it, any rationale for the scoping in the agent
  prompt only, never embedded in the diff. Post its reports like any other
  round, same head SHA.
- **Inert** (unchanged since a head already fully reviewed, or prose with no
  code, config or invariant content) → say so in step 6, naming the region and
  why, rather than letting the marker pass unaddressed.

A `[PROCESS ARTIFACT …]` line is not truncation and needs no follow-up.

## 6. Report

1. Head SHA and PR number (or pre-PR mode).
2. **Code quality**: blocking-issue count, or "review did not run", and the
   model it ran on.
3. **Security**: PASS / FAIL / "review did not run", and the model it ran on.
4. Truncation: none, or what step 5 concluded.
5. Next step: → the `fix-review` skill (it self-fetches both reports) when
   either report carries a blocking issue, a security FAIL, a `## Needs
   broader manual review` item, or a security-relevant non-blocking finding —
   an auth or authorization gap, a credential or token exposure, injection, a
   weakened expiry, or a missing bypass test for one of those. Say which of
   those you saw, since **that is the only thing that drains them** and a
   reader who takes "no blocking issues" for "done" loses them to this
   thread. Name the ones a fix or an existing `docs/deferred.md` entry has
   already drained too, and say so — the reviewers are fresh each round and
   restate those forever, and `fix-review` will stop on a report where
   everything is already drained. Otherwise, with no unresolved truncation
   marker, this head is review-clean and a clean head is a **stop**: no
   voluntary pushes.

Do not fix anything, commit, or merge here — this skill reviews and reports.
