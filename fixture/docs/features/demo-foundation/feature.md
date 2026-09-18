---
status: done
depends-on: []
dark-ship: `widgets.store_enabled`, checked in the service layer before any widget is read or written
checkpoint: The store holds widgets and refuses them when the gate is off
---
# Feature: Widget store and gate

## Goal

Give the fixture one real thing to reason about: an in-memory widget store
and the server-side gate every read has to pass. Closed at v0.1.0; it is here
so that `demo-widget` has a dependency that actually resolves.

## Observable milestone

`add_widget` and `list_widgets` exist, and both refuse when the gate is off.

## Decisions (settled — do not re-ask at plan time)

1. The store is in memory. Persistence is out of scope for the fixture.
2. The gate is a module-level function, not a config file, so a reviewer can
   see it in the diff.

## Chunks

### 1 — Store and gate

- [x] `src/widgets.py` with `add_widget`, `list_widgets` and the gate
- **Invariants:** no read path returns a widget when the gate is off; a
  widget's `owner` is set at creation and never from later input
- **Decisions:** *auto-pick* — data structure, naming. *ask-first* — none
- **Depends-on / must-not-break:** nothing; this is the first chunk
- **Verify:** listing with the gate off returns nothing and raises no error

## Test checkpoint

Run `manual_tests.md` in this folder once every chunk is merged. Signed off
by: fixture author, 2026-09-18.

### The store holds widgets and refuses them when the gate is off

- [x] With the gate on, an added widget comes back from the list
- [x] With the gate off, the list is empty
