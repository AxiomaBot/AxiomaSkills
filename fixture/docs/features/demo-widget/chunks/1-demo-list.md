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

- Automated: one check per invariant, the gate-off case written first.
  The stub test command in `CLAUDE.md` → Commands always passes, so in this
  fixture "the tests are green" proves the plumbing, not the code.
- Verify: with the demo gate off and the store gate on, `demo_list()` returns
  an empty list.

## Manual test steps

- [ ] **Both gates on, the demo list shows the widgets** (1)
  - Steps: `python -c "import src.widgets as w; w.set_gate(True); w.set_demo(True); w.add_widget('a','ada'); print(w.demo_list())"`
  - Expected: one widget named `a` is printed
- [ ] **Demo gate off, the demo list is empty** (1)
  - Steps: same, with `w.set_demo(False)`
  - Expected: an empty list, even though the store gate is on

## Open questions

(none)

Build model: sonnet — one module, no migration
