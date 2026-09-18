---
description: Feature close — measure how a completed feature actually went, default to "no change", propose at most three workflow edits; the only writer of docs/weak-spots.md
argument-hint: <feature>
---

# Retro — close a feature

**Tier:** planning (floor opus) — stop if this session is below it; never
switch the session down. This is the run the "go one up" note in `CLAUDE.md`
is about: deciding that a rule should be *removed* is the judgment call here.

Measure what happened, then decide whether anything should change. **The
expected outcome is "no change".** This workflow's rules are almost all
one-incident scars, and a retro that adds a rule per feature ends in a corpus
nobody reads, at which point every rule in it is weaker, including the ones
that matter. The bar below is deliberately high.

Target feature: **$ARGUMENTS**. If empty, ask which and stop.

## Arguments

- `<feature>` is a folder under `docs/features/`. A **legacy phase** — one
  named in `roadmap.md` → `## Done` with no folder — is also valid: its data
  is the project's own pre-migration archive (e.g. `docs/archive/`) and the
  PRs, and the report says which archived set it read.
- Run after the checkpoint is signed off (`status: done`). Checkpoint-found
  bugs are the one input no review round can give you, so earlier than that
  you are measuring half the feature. Not `done` → say so and ask first.
- The report is `docs/retros/<slug>.md`, matched against `docs/retros/`
  **case-insensitively** — a legacy report may pre-date consistent naming,
  and a case-sensitive check would write a second retro beside one, not
  notice it. **An existing report means this is a replay:** give the report
  in full in chat, write neither file, and ask before replacing it. The
  expiry rule below counts retro runs, so a replay that wrote would age
  every row twice.

## Hard rules

- **The only files you write are the report and `docs/weak-spots.md`.** No
  code, no plugin skill files, no `AGENTS.md`, `CLAUDE.md`, `roadmap.md`, no
  feature or chunk files. Edits to those are *proposals in the report*,
  quoted, for the user to approve — a retro that silently rewrites the process
  it is judging leaves no audit trail.
- **Evidence, not impression.** Every finding cites its PR, its round, and the
  reviewer's or the human's actual wording.
- **Rounds are the metric; blame is not the point.** Never who missed
  something — which stage should have caught it, and what edit makes it catch
  the next one.
- **Every proposal names what it replaces.** A pure addition carries a stated
  reason why nothing could come out to pay for it.

## Gather

1. **The feature's PRs.** The chunks from `feature.md`; the merged PR for each
   via the GitHub tooling in this environment (chunk branches are
   `feat/<feature>-<n>-<slug>`, per the `build` skill). Also the merged PRs in
   the same window carrying no chunk — plan-only PRs, doc fixes, dependency
   bumps, the sign-off. Bound the window by the previous feature's close and
   this feature's sign-off, so the checkpoint's own fixes are inside it.
   **Fail soft:** ask rather than guess — for a PR that will not resolve, for
   GitHub being unavailable, and for a boundary that is genuinely ambiguous
   (features that overlapped, a previous feature with no retro). A guessed
   window silently drops PRs and nothing downstream notices.
2. **The review history per PR.** Every `# Code quality review` and
   `# Security review verdict` comment in order, with the head SHA from its
   `Reviewed head:` line. A pre-redesign PR may carry a legacy marker with no
   `Reviewed head:` line — date it from the comment timestamps. A **round** is
   a push made in response to a blocking verdict; a PR that merged on its
   first pair of verdicts is 0 rounds. Record each blocking issue verbatim with
   its resolution: fixed / disagreed with evidence / escalated. A head with no
   report for its SHA is an *unreviewed* head, and counting it as clean is the
   error this step exists to avoid.
   On each PR's **final** head, also check that every security-relevant
   non-blocking finding and every `## Needs broader manual review` item ended
   in a fix, a `docs/deferred.md` entry, or a verification in the thread. That
   drain rule is what this workflow relies on in place of a harvest step, and
   this is the only thing that audits it; one left in a thread is a finding
   here whatever else went well.
3. **The checkpoint result.** Which `manual_tests.md` items failed, and every
   bug the human found that both reviews missed — the defects the process as
   it stands does not catch, and the most valuable rows here.
4. **Human interventions, per chunk.** Escalations from the `auto-chunk`
   skill, questions the `plan` skill had to ask twice, anything the human
   fixed by hand.
5. **Assumptions that turned out wrong.** Each chunk file's `## Assumptions
   (revisit if wrong)` from an `--auto` plan — which were wrong, and the cost.
6. **The milestone.** Did the feature ship the observable milestone
   `feature.md` states, as stated? Name the gap if not.
7. **`docs/weak-spots.md` as it stands**, and which of its rows fired here.

## Decide

Default to no change. Propose a rule only when one of these holds, and say
which one in the proposal:

- the class **recurred across two features** — name both; or
- it **cost multiple rounds** in this feature; or
- it is a **security class**.

Everything else is a one-off. Name it under "Within normal variance" with the
literal line `noted, no rule`. A single mistake, however irritating, is
variance until it repeats.

**At most three proposals**, each quoting the lines it replaces. Prefer a
replacement or a narrowing over an addition; a rule that has not fired since
the incident that created it is a removal candidate in its own right, and its
founding anecdote is not evidence that it still works. Cut prose for a
deterministic check (`pr-guards.yml`, CI, a test) only once that check exists
and has been seen to fail on a real violation.

## Weak spots

You are the only writer of `docs/weak-spots.md`, and these edits are applied,
not proposed. Keep them minimal:

- **Last fired** → this feature, for every row that fired here (as a blocking
  issue, a checkpoint bug, or a review finding of that class).
- **Add** a row only at the same bar as a proposal above, with a tag
  (`security` / `data-integrity` / `correctness`) and a *what to check* line a
  reviewer can act on with no other context. At the 30 cap, something comes out
  in the same edit.
- **Expire** a row that has not fired in the last two retros, and say so in
  the report. A `security` row comes out only with a stated reason.

## The report — `docs/retros/<slug>.md`

About 100 lines. Much longer and you are writing the feature's history instead
of its lesson.

```markdown
# Retro — <feature>
*Date: <date> · PRs: <#, #, …> · Data: <feature folder | the archived set>*

| Chunks | Rounds | Blocking | Checkpoint-found bugs | Human interventions | Calendar days |
|--------|--------|----------|-----------------------|---------------------|---------------|

## What happened
<the stated milestone first, then a paragraph per notable event citing PR and
round. "Nothing notable" is a valid paragraph, and the common one.>

## Within normal variance
- <the one-off, named, with its evidence> — noted, no rule

## Proposed edits (max 3)
- **<file>** — <the change> replacing <quoted current lines> — because <class>
  recurred in <feature A> and <feature B> / cost <n> rounds in <chunk> / is a
  security class

## Weak spots
- added: <class> (<tag>) · expired: <class> (<reason if security>) · unchanged
```

## Finish

In chat: the metrics row; the single biggest finding; each proposal as a
numbered item (what, what it replaces, the class and where it recurred); the
weak-spot edits you applied; and the **net line change to the rule corpus**
the proposals would make — added minus removed, said out loud, because
approval time is the only place that growth is ever checked.

**Zero proposals is a result, not a failure — report it as one.** Do not apply
a proposal and do not open a PR for one: approved edits are a small PR of
their own, and a spec-shaped finding is input for the `roadmap` skill's
`refine` mode.
