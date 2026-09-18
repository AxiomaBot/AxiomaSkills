# Deferred

**Actionable only.** An entry is something a future chunk can pick up and
finish: a bug, a cleanup, a missing test. Decision records do not live here —
they live in the feature file that made them, or in `AGENTS.md`.

Format, one entry per heading:

```markdown
### <title>
- **Found:** <feature>/<chunk> or the PR it came out of
- **What:** <one or two sentences>
- **Why not now:** <what put it out of the chunk's scope>
```

---

### Widget list is unsorted

- **Found:** demo-foundation/1
- **What:** `list_widgets` returns insertion order. Callers that expect a
  stable alphabetical order have to sort it themselves.
- **Why not now:** No caller needed an order yet, and picking one is a
  product call.
