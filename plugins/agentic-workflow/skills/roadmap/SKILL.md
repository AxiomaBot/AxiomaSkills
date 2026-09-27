---
description: Plan-stage skill — create the roadmap, detail one feature into chunks with specs, or fold a change in as a diff. Attended only.
argument-hint: init | detail <feature> | refine <new goal or change>
---

# Roadmap — develop and maintain the plan

**Tier:** planning (floor opus) — stop if this session is below it; never
switch the session down. Recommend one model up for an `init` or `refine`
with open product questions.

Where the `plan` skill turns one chunk into a build contract, this skill
develops the plan itself: `roadmap.md` (direction and the feature index) and
each `docs/features/<slug>/feature.md` (goal, decisions, chunks with specs,
the checkpoint). A plan is a set of decisions, not a document: force the
user's judgment out at the right time, and refuse to spec what it is too
early to spec. A fluent plan that quietly made a product decision for the
user is a failed plan.

## Arguments

- `init` — create or ground-up restructure the roadmap.
- `detail <feature>` — turn an `outlined` feature into a `planned` one: its
  folder, its chunks, their specs.
- `refine <goal or change>` — fold a new goal, pivot or retro finding in as
  a diff.

Missing or ambiguous → ask which before doing anything else.

## Hard rules

- **Attended only.** No `--auto` mode; refuse one, or an unattended pipeline:
  the user's judgment is the input.
- **Writes:** `roadmap.md`, `docs/features/<slug>/feature.md` (creating the
  folder in `detail`), and — `refine` only — one dated line appended to
  `docs/roadmap_changelog.md`. No code, tests, or other docs; you may
  *recommend* `docs/deferred.md` entries in the report.
- **Merged history is immutable at the chunk level.** Never edit, delete or
  reword a chunk whose boxes are ticked, and never backdate an unrun
  checkpoint. The unbuilt remainder of a feature is what `refine` operates
  on: reorder, add, remove, rewrite it like any unbuilt work.
- **Graded horizon.** Chunks and specs exist only for the current or next
  feature. The one after gets an outline (goal, milestone, checkpoint name,
  dependencies) in `roadmap.md`; everything beyond gets one paragraph. Detail
  written before the code it must fit exists is how a plan rots — push back.
- **Product decisions belong to the user.** Every fork gets labelled
  *auto-pick* (an engineering default the builder may take) or *ask-first*
  (a product call). When in doubt it is ask-first — `AskUserQuestion` now,
  in this session, not a marker for later.

## Orientation (all modes)

Read `AGENTS.md`, `ARCHITECTURE.md` (or this project's equivalent),
`roadmap.md`, every feature file at `building` or `built`,
`docs/deferred.md`, and the newest file in `docs/retros/`. Skim code only to
test whether an outline still matches it. Before proposing anything, report:
features at `built` whose checkpoint has not been signed off (the user
decides whether to plan on top of them), and every live **interim
invariant** — a deliberately temporary design with a named replacement — and
where its expiry is scheduled.

## Mode: `init`

1. **Interview** with `AskUserQuestion`, in this order: the product goal in
   one sentence; the users and what each must be able to do; hard constraints
   (stack, budget, scale, hosting); explicit non-goals; what is decided vs
   open; the riskiest assumption. Keep asking until a wrong guess is
   impossible, not merely unlikely.
2. **Decompose into features as vertical slices.** Each ends with something
   the user can observe and exercise by hand. Order by risk and dependency:
   the riskiest assumption is tested by the earliest feature that can. Fill
   each row's `After` cell with the features it cannot start before,
   comma-separated; empty means it can start now. That is what shows which
   features can be built in parallel long before any of them has a folder.
3. **Apply the horizon**, run the pre-mortem, write `roadmap.md` from
   `${CLAUDE_PLUGIN_ROOT}/templates/roadmap.md` and `detail` the first
   feature.

## Mode: `detail <feature>`

The rolling-wave step — run when a feature is about to start, not before.

1. Confirm the target is the next `outlined` feature. Surface unrun
   checkpoints first and let the user decide.
2. Re-test the outline against the current code: what changed since it was
   written? Which Actionable `docs/deferred.md` entries belong here? Which
   interim invariants expire here and must be replaced by a chunk? Fold the
   answers in, asking about anything that is a product call.
3. **Declare the dependencies and the gate.** `depends-on` lists the chunks
   of other features this one needs, as `<feature>/<n>`; the `plan` skill
   refuses to start until each is on `main`. Start from the row's `After`
   cell: each feature named there becomes the specific chunks this one needs
   from it, and a feature it turns out not to need comes off the cell. Two features merge into one
   only when B cannot be manually tested without all of A *and* A has no
   user-visible value without B. `dark-ship` names the **server-side**
   enforcement point that keeps the feature invisible until sign-off — a
   config gate, a route guard, an opt-in checked in the service layer, named
   as a backticked code reference. `workflow check` rejects free prose and
   template-only references, but it only checks the *shape of the claim* —
   that the gate exists, is reached on every path and defaults off is yours
   to confirm here and the reviewers' to judge. A feature that genuinely
   cannot ship dark says `feature branch`; only one such feature is in
   flight at a time, which nothing mechanical enforces.
4. **Cut chunks**: one coherent slice each, sized so the PR diff gets one
   complete review (one feature slice, one migration, *or* one script sweep —
   not all three). State the order and why.
5. **Write each chunk's spec block** (template below). The Invariants line is
   the most valuable line in this workflow: stated here, it is satisfied
   before review; unstated, the review finds it one round at a time.
6. Pre-mortem, fix what it finds, create `docs/features/<slug>/`, write
   `feature.md` from `${CLAUDE_PLUGIN_ROOT}/templates/feature.md`, and flip
   the `roadmap.md` row to `planned` with its link.

## Mode: `refine <goal or change>`

1. Restate the change and confirm it. Classify it: new goal / scope change /
   retro consequence / reality-drift correction.
2. Propose a **diff**, never a rewrite: which outlines it perturbs, which
   chunks it adds, removes or reorders, which non-goals it touches. Show it
   before writing anything.
3. Run the consequence checks and state each result: does it **orphan an
   interim invariant** (reschedule the replacement explicitly)? **Invalidate
   an unrun checkpoint** (name the affected items)? **Break a `depends-on`**
   of any planned chunk, or an `After` cell of any outlined feature?
4. Append one dated line — what changed and why — to
   `docs/roadmap_changelog.md`, so a refinement is never silently absorbed.
5. Apply the agreed diff.

## The pre-mortem (before every write)

- Does every feature end with an **observable milestone**?
- Does every chunk state its **invariants**, including what must be refused?
- Are dependencies explicit `After` cells, `depends-on` entries and
  `Depends-on / must-not-break` lines, never prose the reader must infer?
- Is any **product decision disguised as an auto-pick**? Would the user care
  which way it goes? Then ask now.
- Which later feature could invalidate this design? Resequence, or record the
  interim invariant with a locking test and a named expiry.
- Is any chunk too big for one complete review?
- Walk one real user journey through the chunk order: is the app broken for
  a user at any point between checkpoints?
- **Is every factual claim about existing code true?** Open each cited file
  and confirm the *behaviour* on the path in question, not that the symbol
  exists. Cite the enforcement point — the call site, route, or test — or say
  plainly that nothing enforces it.
- Does an ops precondition (a backup, a restore rehearsal, a dashboard
  setting) say **where its completion is recorded**? Otherwise a satisfied
  gate and a skipped one look the same a week later.
- Do any two parts of the feature contradict each other? Read the order
  rationale against every chunk's tasks and invariants.

## Templates

The chunk's spec block, embedded under each `### <n> — <name>` heading in
`feature.md` (full shape in `${CLAUDE_PLUGIN_ROOT}/templates/feature.md`):

```markdown
### <n> — <name>
- [ ] <task>
- **Invariants:** <properties that must stay true, incl. what must be refused>
- **Decisions:** *auto-pick* — <forks with a recorded default>. *ask-first* —
  <product calls, resolved in the plan skill's conversation>
- **Depends-on / must-not-break:** <prior chunks, files, invariants>
- **Verify:** <the one runtime behaviour /verify exercises>
- **Build model:** <optional — set when the reason is already known>
```

Outline (in `roadmap.md`): goal, observable milestone, checkpoint name,
known dependencies — no chunks, no specs. Intent: one paragraph.

## Finish

1. Confirm the written plan passes the pre-mortem and respects the horizon;
   run the `workflow` skill's `check` mode.
2. Report: what changed, every decision the user made and every auto-pick
   you recorded, which interim invariants are live and where each expires,
   which checkpoints they are building on top of.
3. Land it as its own small PR — a plan bug is the cheapest bug this project
   fixes, and the `pr-review` skill reviews plan-only PRs like any other.
   Note what the reviewers see: `roadmap.md` and `feature.md` are fully in
   the diff, while a chunk file's content is withheld as a process artifact
   (`review_context.py` → `OMIT_PATTERNS`). So a decision you want a
   reviewer's eyes on belongs in the feature file, not only in a chunk file.
   Next: `plan <feature> <chunk>` or `auto-chunk <feature> <chunk>`.
