# CLAUDE.md — demo-shop (fixture)

A toy project that exists only so a change to an `agentic-workflow` skill can
be exercised end to end without risking a real repository. Nothing here is a
real product; the commands below are stubs that always succeed.

## Commands

```bash
# Lint (stub — always passes)
echo "lint: ok"

# Format (stub — always passes)
echo "format: ok"

# Test (stub — always passes)
echo "tests: 0 passed"
```

A real project puts its own lint, format and test commands here. Every skill
that runs a check reads them from this section rather than assuming a
toolchain, which is exactly what the stubs above are here to prove.

## Models

Order, weakest first: haiku < sonnet < opus < fable (the current Claude
model families; extend the line when a new one ships).

| Tier | Floor | Recommended | Go one up when |
|------|-------|-------------|----------------|
| planning | opus | opus | the feature touches auth, tokens, the data model, or a migration; a roadmap `init`/`refine` with open product questions; a retro that proposes removing rules |
| coding | sonnet | sonnet | the chunk file says so; the chunk touches shared services, a migration, or concurrency; the previous chunk in the same subsystem bounced in review |
| fix-review | sonnet | opus | always recommended: disagreeing with a reviewer on evidence needs judgment |
| quality review | sonnet | sonnet | the diff changes the review contract itself, or `--model` is passed to the `pr-review` skill |
| security review | opus | opus | — |

An attended skill stops if the session model is below its tier's floor and
never switches a session down. Spawned agents receive the tier's model
explicitly: the recommended one by default, or the override.

## Layout

`roadmap.md` is the plan of record. A feature's goal, decisions, chunks and
checkpoint live in `docs/features/<slug>/feature.md`. The workflow itself is
described by the `agentic-workflow` plugin's README, not here.
