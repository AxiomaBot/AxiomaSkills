Three `##` headings for the project's `AGENTS.md`, each read by name by a
skill or a reviewer agent. The `workflow` skill's `init` mode writes this
skeleton; the content under each heading is the project's own and grows over
time — nothing here is copied from another project.

```markdown
## Domain rules for code review

The rules below are what the PR reviewer agents enforce when reviewing PRs
(`agents/quality-reviewer.md` and `agents/security-reviewer.md` read this
section by name). State the business rules and authorisation model the code
must hold to — the game rules, not implementation notes.

- <rule>

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
- <how this project actually ships: tag format, CI, deploy trigger>

---

## Weak spots

The repo-specific classes of mistake that have recurred here live in
`docs/weak-spots.md`, written **only** by the `retro` skill. Both reviewer
agents and the `build` skill's self-review read it from there.
```
