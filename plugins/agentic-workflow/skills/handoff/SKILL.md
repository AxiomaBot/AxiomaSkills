---
description: Pre-PR bookkeeping for a built chunk — fold its manual test steps into the feature's checklist, tick its boxes, set the feature status, update the roadmap.md index row
argument-hint: <feature> <chunk>
---

# Hand off a chunk

**Tier:** coding (floor sonnet) — stop if this session is below it; never
switch the session down.

Runs once per chunk, after the build and **before the PR opens**, so the
bookkeeping is in the same diff the reviewers see and reaches `main` with the
merge. It writes exactly three files: `docs/features/<feature>/manual_tests.md`,
`docs/features/<feature>/feature.md` (task boxes and `status` only, never
prose or scope), and `roadmap.md` (the feature's index row only). No code, no
`docs/deferred.md`, nothing else. There is no non-chunk mode: a PR with no
chunk has nothing to hand off.

## Steps

1. **Read** the chunk file's Tasks and Manual test steps; the feature file's
   `## Test checkpoint` (which named checkpoint this chunk feeds) and this
   chunk's task list; `git diff origin/main --stat` to see what actually
   landed. Skim the code so the steps match reality.
2. **Fold the Manual test steps into `manual_tests.md`.** Create it from the
   template below if absent. The file reads like a tester's plan for the whole
   feature — organised by checkpoint, then by session (the items that can
   be run in one sitting because they need the same things), converged to
   final-state assertions — not a log of what each chunk produced:
   - A chunk whose steps are `None — <why>` adds no item.
   - An item goes under the session its `Needs:` line names; one with no
     `Needs:` line goes in the default-setup session, which comes first. The
     session heading states what it needs, once, and is the only record of
     why an item sits there: the item's own `Needs:` line is not copied in.
     A credential is named in the heading, never written out.
   - A flow several chunks touched gets **one** item asserting the final
     behaviour; superseded intermediate checks go.
   - "Still loads / unaffected" appears once per flow, not once per chunk.
   - Migration-log and schema-shape checks sit under an **upgrade-only**
     heading a fresh-database tester can skip.
   - Consolidation removes redundancy, never coverage: every distinct
     behaviour keeps an item; when unsure whether two are the same, keep both.
   - Each item carries its chunk tag so a failure points somewhere.
   - An ops step a chunk gates on (a restore rehearsal, a dashboard setting)
     gets an item with a place for the dated completion line the spec asks
     for — the record is the only evidence that step happened.
   - A command that produces a cookie jar, a page with a CSRF token, a token,
     or a `.env` value writes it to an absolute path outside the repo, stated
     in the step. Never a repo-relative filename.
   - Never reword or re-collapse an already-checked item; that is tested
     history.
3. **Tick the boxes.** Under the chunk's `### <n> — <name>` heading, `- [ ]`
   → `- [x]` for every task this build completed. A task not done (scope
   changed, deferred) stays unchecked and is named in the report. Never touch
   the `## Test checkpoint` boxes or its `Signed off by` line — those record
   the human's manual sign-off.
4. **Set the status.** In the feature file's frontmatter and the matching
   `roadmap.md` row: `planned` → `building` when this is the first chunk to
   land; `building` → `built` when every chunk's boxes are now all ticked.
   Never `done` — that is the human's, at sign-off, together with the tag.
   **The one way a status moves backwards:** new unchecked items landing in a
   feature the human already signed off. `done` → `built` then, in both
   places at once — and in `roadmap.md` that means **moving the row out of
   `## Done` and back into `## Features`** carrying the new status, because
   `## Done` has no status column and a folder linked from there reads as
   `done` whatever the feature file says. Say so at the top of the report:
   the human signed that feature off once and has to know it is carrying
   untested work again.
   A feature reading `done` over an unchecked checklist is the one state this
   bookkeeping exists to prevent, and nothing mechanical catches it: the
   layout check only tests that the two files agree, and they would both be
   wrong together. Their already-checked items stay checked.
5. **Make the checkpoint runnable** — only when this chunk is the last one
   feeding its checkpoint: every chunk the feature file puts in that
   checkpoint's range now has all its boxes ticked. For a feature with one
   checkpoint that is when the status just went to `built`; when the feature
   file does not say which chunks feed which checkpoint, wait for `built`.
   Until then no one can see the whole list. Read that
   checkpoint's items together, against its `Needs:` line in the feature
   file:
   - Order the sessions by what they take to arrange: default setup first,
     then credentials, then anything that waits on the real world or on a
     release.
   - Every item's starting state is stated and reachable from its session's
     setup. Two items that need the same record, account or fixture in
     different states each get their own, named in the steps.
   - A need the feature file's `Needs:` line does not declare is a cost the
     human has not agreed to: name it in the report.
   This step reorders and completes; it never drops an item, and it never
   decides where to test, what to pay for or what to skip — those go in the
   report as questions.
6. **Report.** Which checklist items were added, converged or collapsed;
   which boxes were ticked and which deliberately not; the status transition
   if any; what step 5 found, when it ran. Remind the reader that the
   checklist is run session by session when the checkpoint is reached — not
   now — and that marking the feature `done` is theirs.

## Template

```markdown
# Manual tests — <feature name>

> **When to run:** once every chunk in a checkpoint's range is merged and CI
> is green, one session at a time, in the order below.
>
> **Setup:** <the default: env / seed steps, how to run the app>

## <Checkpoint name>

### <Session — what it needs, e.g. "Local, no credentials">
- [ ] **<short title>** (<chunk tag>)
  - Steps: <exact clicks / commands / URLs / inputs>
  - Expected: <observable result>

### Upgrade-only
- [ ] ...
```
