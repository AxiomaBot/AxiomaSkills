---
description: Plan one chunk — resolve every question, derive its invariants, write the build contract to docs/features/<slug>/chunks/<n>-<slug>.md
argument-hint: <feature> <chunk> [--auto]
---

# Plan a chunk

**Tier:** planning (floor opus) — stop if this session is below it; never
switch the session down. Recommend one model up when the chunk touches auth,
tokens, the data model or a migration; a recommendation, not a switch.

Your job is to leave behind a chunk file the `build` skill can execute
unattended: every fork resolved, every **invariant** stated. Invariants are
the negative-test targets — what must stay true, including what must be
*refused*. One stated here is satisfied before the PR opens; one left
unstated is what the reviewers find, one round at a time.

## Arguments

1. If `$ARGUMENTS` contains `--auto`, remove it and run in autonomous mode
   (below). Never let the token reach the lookup.
2. `<feature>` is a folder under `docs/features/`; `<chunk>` is the `<n>` of
   a `### <n> — <name>` heading under that file's `## Chunks`, matched
   exactly. **No ordinal fallback and no prefix match** — in a feature whose
   chunks are `8.1`–`8.10`, reading a bare `8` as "the eighth" would plan a
   chunk nobody asked for and say nothing unusual happened. No exact match →
   list the headings and stop.
3. No folder, no such heading, or nothing given: attended, ask; `--auto`,
   stop. A feature with no folder needs the `roadmap` skill's `detail` mode
   first, which is attended by design.

## Gates — before anything else

- **Dependency gate.** `git fetch origin main`. For each `depends-on` entry
  `<feature>/<n>` in the feature file's frontmatter, read
  `git show origin/main:docs/features/<feature>/feature.md` and require that
  chunk's heading to carry **at least one** task box and every box under it to
  be `[x]`. Stop and name the entry when a box is unticked, when the heading
  carries no box at all, when the heading is not there, or when the command
  fails because that feature has not reached `main` at all — the last is the
  one most easily misread as a tooling error. Dependencies are declared,
  never stacked.

  **The no-box case is a stop, not a pass.** "Every box is ticked" is
  vacuously true of a chunk whose tasks were written as prose, so reading it
  as landed would let this feature build on something that never shipped —
  and this gate is the whole mechanism replacing stacked branches. Nothing
  mechanical backs it up: `workflow check` requires chunk headings, not
  boxes under them.

  **Say which of the two you hit**, because they need opposite responses. A
  chunk that has not landed is waiting: come back when it does. A chunk that
  *has* landed but kept an unticked box is a task the `handoff` skill
  recorded as deliberately not done, and that box never ticks itself — so the
  gate would refuse this feature forever. That one is not yours to wave
  through: say the dependency needs the `roadmap` skill's `refine` mode to
  drop the abandoned task from its feature file first, since a box nobody
  will ever tick is a false claim of pending work, and stop. `--auto`:
  escalate it the same way.
- **Already merged?** If this chunk's own heading on `origin/main` carries at
  least one box and they are all ticked, there is nothing to plan; stop and
  say so. A heading with no boxes is not "merged" — it is a chunk the
  `roadmap` skill's `detail` mode wrote in prose, which is exactly what you
  are here to plan.

## Hard rules

- The only file you write is the chunk file. No code, tests, templates,
  config, or other docs.
- Attended, this is the one conversation in the sequence; the `build` skill
  runs with auto-accept, so anything ambiguous here becomes a silent guess
  there. Drive ambiguity to zero.
- **`--auto`:** no one to ask. Never call `AskUserQuestion`. Resolve every
  fork with the lowest-risk default that fits the codebase and the feature's
  Decisions, and record it. Leave a `[?]` only for a product decision with no
  safe default — the feature file's *ask-first* items are exactly these — and
  if any remains the chunk is **not build-ready**: report the markers, don't
  report it ready.

## Steps

1. **Orient.** `AGENTS.md`; `ARCHITECTURE.md` (or this project's
   equivalent); the feature file in full — Decisions (settled, never
   re-ask), release and sequencing notes, this chunk's task list and spec
   block (`Invariants`, `Decisions`, `Depends-on / must-not-break`,
   `Verify`, an optional `Build model`), and which named checkpoint the
   chunk feeds; `docs/weak-spots.md`; `docs/deferred.md` for Actionable
   entries naming this feature or chunk; the code the chunk touches.
2. **Deferred work.** Offer each relevant Actionable entry (`--auto`: fold in
   only what is clearly in scope and low-risk; record what you took and
   skipped). An entry you take is listed in the chunk file and closed in place
   by the PR that lands it.
3. **Invariants.** Start from the spec's `Invariants` line and expand it from
   what the code shows. With no spec line, derive them: what must be refused
   (an unauthorised caller, a cross-boundary read, a reused token, a double
   submit), what prior behaviour must not regress, and which
   `docs/weak-spots.md` rows this chunk's surface touches. An invariant that
   is really a product call is a question, not a conclusion.
4. **Ask everything, once.** Scope, edge cases, library choices, UI, what is
   explicitly out — gather it all and ask in one pass with `AskUserQuestion`.
   Keep asking until nothing is ambiguous. (`--auto`: decide and record.)
5. **Verify every claim about existing code.** For each "this already
   happens", "X is guarded", `file:line` — open it and confirm the
   *behaviour* on the path in question, not that the symbol exists. Cite the
   enforcement point (the call site, route, or test), or say plainly that
   nothing enforces it.
6. **Pick the models.** `Build model:` defaults to the coding recommendation
   (`CLAUDE.md` → Models). Raise it one when the spec pre-sets it, the chunk
   touches a shared/core service, a migration, or concurrency, or the
   previous chunk in the same subsystem bounced in review. Add
   `Review model:` when the diff deserves both reviewers above their floors
   (the token path, authorisation, the release path).
7. **Write the chunk file** to
   `docs/features/<feature>/chunks/<n>-<slug>.md`, from
   `${CLAUDE_PLUGIN_ROOT}/templates/chunk.md`, overwriting a previous plan
   for the same chunk.
8. **Gate check.** No `[?]`; Invariants populated or literally `None — <why>`
   (a chunk with no runtime surface); Manual test steps present; `Build
   model:` line present. Report: what was decided (attended) or assumed
   (`--auto`), the invariants, the models, and the next step —
   `build <feature> <chunk>` on the build model with auto-accept on.
