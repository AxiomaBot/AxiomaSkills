---
status: building
depends-on:
  - demo-foundation/1 (on main)
dark-ship: `widgets.demo_enabled`, checked in `src/widgets.py` before any demo list is returned; the caller only mirrors it
checkpoint: A demo caller sees the widget list, and only behind the gate
---
# Feature: Demo widget list

## Goal

Expose the stored widgets to a demo caller, behind its own gate, so the
fixture carries one feature that is genuinely mid-flight: a chunk planned,
a build contract written, a checkpoint not yet run.

## Observable milestone

`demo_list()` returns the widgets a demo caller may see, and returns nothing
at all when `demo_enabled` is off.

## Decisions (settled — do not re-ask at plan time)

1. The demo gate is separate from the store gate. Turning the store on must
   not turn the demo on.
2. The demo list is read-only. Creating widgets stays on the foundation API.

## Chunks

### 1 — Demo list behind its own gate

- [ ] `demo_enabled` and `demo_list` in `src/widgets.py`
- [ ] A refusal check for the gate-off path
- **Invariants:** `demo_list` returns nothing whenever `demo_enabled` is
  false, including when the store gate is on; no caller-supplied argument can
  turn the demo gate on
- **Decisions:** *auto-pick* — return type, error text. *ask-first* — whether
  the demo list may include another owner's widgets
- **Depends-on / must-not-break:** demo-foundation/1's store and its gate;
  the existing `list_widgets` behaviour is unchanged
- **Verify:** with the demo gate off and the store gate on, `demo_list()`
  returns an empty list
- **Build model:** sonnet — one module, no migration

## Test checkpoint

Run `manual_tests.md` in this folder once every chunk is merged. Signed off
by: <human, date>.

### A demo caller sees the widget list, and only behind the gate

- [ ] With both gates on, the demo list shows the stored widgets
- [ ] With the demo gate off, the demo list is empty even though the store
      gate is on
