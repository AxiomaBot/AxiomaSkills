# Chunk 1 — Demo list behind its own gate (demo-widget)

## Goal

Expose the stored widgets to a demo caller through `demo_list()`, gated by
`demo_enabled` and by nothing else.

## Invariants (negative-test targets)

- `demo_list()` returns an empty list whenever `demo_enabled` is false, even
  when the store gate is on.
- No argument to `demo_list()` can turn the demo gate on.
- `list_widgets()` behaves exactly as it did before this chunk.

## Decisions resolved

- May the demo list include another owner's widgets? → Yes; the fixture store
  has no per-owner visibility rule, and adding one is `demo-export`'s problem.
- What does `demo_list()` return when the store is empty? → An empty list,
  the same shape as the gate-off case.

## Tasks

1. Add `demo_enabled` and `set_demo` — files: `src/widgets.py`
2. Add `demo_list`, checking the demo gate before the store — files:
   `src/widgets.py`
3. Add the gate-off refusal check — files: `src/widgets.py`

## Deferred items pulled in

- none

## Out of scope

- Sorting the list (`docs/deferred.md` → "Widget list is unsorted").
- Any persistence, and any HTTP surface.

## Test strategy

- Automated: one check per invariant, the gate-off case written first. The
  gate-on round trip and the gate-off refusal are these checks, which is why
  neither is a manual item below.
  The stub test command in `CLAUDE.md` → Commands always passes, so in this
  fixture "the tests are green" proves the plumbing, not the code.
- Verify: with the demo gate off and the store gate on, `demo_list()` returns
  an empty list.

## Manual test steps

- [ ] **The demo list shows only what a demo visitor should see** (1)
  - Steps: from `fixture/`, with nothing stored yet, run
    `python -c "import src.widgets as w; w.set_gate(True); w.set_demo(True); w.add_widget('kettle','ada'); w.add_widget('lamp','grace'); print(w.demo_list())"`
    and read the output as a visitor who owns neither widget.
  - Expected: you are content for that visitor to see every name and owner
    printed. Anything you would rather keep private is a failure.

## Open questions

(none)

Build model: sonnet — one module, no migration
