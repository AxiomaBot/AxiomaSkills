# AGENTS.md — demo-shop (fixture)

## Project context

`demo-shop` is a fixture: a one-module toy that lists widgets behind a
server-side gate. It exists so that a change to an `agentic-workflow` skill
can be run against a project that satisfies the layout, without touching
anything real. Treat every rule below as illustrative — a real project writes
its own.

## Domain rules for code review

The rules below are what the PR reviewer agents enforce when reviewing PRs
(`agents/quality-reviewer.md` and `agents/security-reviewer.md` read this
section by name).

- No widget is read or written unless `widgets.store_enabled()` is true, and
  no widget reaches a demo caller unless `widgets.demo_enabled()` is true as
  well. There is no ungated read path.
- A widget's `owner` is assigned once, at creation, and is never taken from
  caller-supplied input on any later call.
- Nothing in this project logs a caller identifier alongside a widget body.

---

## Release model

- **Trunk, no feature branches.** Every chunk merges to `main`, and `main` is
  always tag-able. A feature that genuinely cannot ship dark may use a
  feature branch, and only one such feature may be in flight at a time.
- **Dark-shipping is the isolation mechanism.** Each feature is invisible to
  users until its checkpoint is signed off. The feature file's `dark-ship`
  line names the **server-side** enforcement point — a config gate, a route
  guard, an opt-in checked in the service layer. UI concealment alone does
  not qualify.
- **One PR per chunk**, reviewed on its own head. A clean head is a stop.
- **The human's manual checkpoint is the only gate before a release.**
- Merging to `main` ships nothing. A `v*` tag is the only thing that does —
  in this fixture there is no deploy at all, which is the point: the release
  step is a no-op you can exercise safely.

---

## Weak spots

The repo-specific classes of mistake that have recurred here live in
`docs/weak-spots.md`, written **only** by the `retro` skill. Both reviewer
agents and the `build` skill's self-review read it from there.
