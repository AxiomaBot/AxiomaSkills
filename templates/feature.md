---
status: planned
depends-on:
  - <feature>/<n> (on main)
dark-ship: <server-side enforcement point; or: feature branch>
checkpoint: <name, or a list when the feature has several>
---
# Feature: <name>

## Goal
## Observable milestone
## Decisions (settled — do not re-ask at plan time)
1. ...

## Chunks
### <n> — <name>
- [ ] <task>
- **Invariants:** <properties that must stay true, incl. what must be refused>
- **Decisions:** *auto-pick* — <forks with a recorded default>. *ask-first* —
  <product calls, resolved in /plan's conversation>
- **Depends-on / must-not-break:** <prior chunks, files, invariants>
- **Verify:** <the one runtime behaviour /verify exercises>
- **Build model:** <optional — set when the reason is already known>

## Test checkpoint
Run `manual_tests.md` in this folder once every chunk is merged. Signed off
by: <human, date>.
### <Checkpoint name>
- [ ] <manual assertion>
