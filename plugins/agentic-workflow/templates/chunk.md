# Chunk <n> — <name> (<feature>)

## Goal
<one or two sentences from the feature file>

## Invariants (negative-test targets)
- <property, including what must be refused>

## Decisions resolved
(--auto: "## Assumptions (revisit if wrong)" — every default and why)
- <question> → <answer>

## Tasks
1. <task> — files: <paths>

## Deferred items pulled in
- <entry title from docs/deferred.md> (or: none)

## Out of scope
- <deliberately not done here>

## Test strategy
- Automated: <what pytest covers, per task; the adversarial test per invariant>
- Verify: <the one runtime behaviour /verify exercises, from the spec>

## Manual test steps
(only what needs a human: their judgement, the physical world, or an account
or machine only they have — written for the tester, in the product's words.
A result a command can check is an automated test above, not an item here.
`None — <why>` when nothing needs a human. /handoff folds these into the
feature's manual_tests.md, under the checkpoint this chunk feeds;
upgrade-only checks marked as such)
- [ ] **<title>** (<n>)
  - Needs: <only when it takes more than the default setup — a credential
    (named, never its value), production, a real-world event>
  - Steps: <the starting state and how to reach it, then the exact clicks /
    commands / URLs / inputs>
  - Expected: <observable result>

## Open questions
(must be empty — [?] only for a product decision with no safe default)

Build model: <model> — <why>
Review model: <model> — <why>   (optional)
