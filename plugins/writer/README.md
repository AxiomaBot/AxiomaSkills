# writer

One agent, `writer`, that writes, rewrites or summarises prose in a plain, honest,
peer-to-peer voice. Reach for it whenever the words matter and the reader is a person: an
evidence or work record, an analysis note, a report section, a CV or cover-letter paragraph,
an orientation summary, an email that has to read as human rather than generated.

## Why it exists

Most model-written prose fails the same way regardless of subject: it reaches for the
ready-made phrase instead of the plain word, dresses ordinary work up as something grander, and
drifts into a register the person who did the work would never speak in. `writer` is built
against that failure mode directly — it carries Orwell's six rules and the reasoning behind
them, plus a word-choice test aimed at the two ways register drifts even when every individual
word is correct English: reaching for a report-and-management word for something the author
lived through directly, and letting a metaphor take over from the plain noun it stands in for.

## Using it

Install the plugin, then delegate a writing task to the `writer` subagent with:

- **job** — `write`, `rewrite`, or `summarise`.
- **source or draft** — inline text or a file path.
- **genre** — record/narrative, analysis, persuasive record, reference/orientation, or
  correspondence (it infers one if you don't say).
- **author** (optional) — whose voice this is, for the register test.
- **output** (optional) — a path to write the result to.

```
Use the writer agent: job rewrite, genre record, author <name>, source
wiki/evidence/draft.md, output wiki/evidence/draft.md.
```

It reads only what it is given, plus one project style file if present — never the rest of the
repository — so a draft never picks up a phrase or a fact that does not belong to it.

## Specialising it for a project

Add a `writing-style.md` at the consuming project's repo root (or `.claude/writing-style.md`)
and the agent treats it as authoritative on top of its own defaults: house genre floors,
register examples calibrated to the team's own vocabulary, a technical-term allowlist, and
formatting rules all override the built-in method where they conflict. Nothing in the agent
itself is specific to one project, one domain, or one house style — the override file is how a
team makes it theirs.
