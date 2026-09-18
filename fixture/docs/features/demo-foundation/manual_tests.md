# Manual tests — demo-foundation

The checkpoint checklist for this feature, folded in one chunk at a time by
the `handoff` skill. Final-state assertions, not a per-chunk log.

## The store holds widgets and refuses them when the gate is off

- [x] **Gate on, widget round-trips** (1)
  - Steps: `python -c "import src.widgets as w; w.set_gate(True); w.add_widget('a','ada'); print(w.list_widgets())"`
  - Expected: one widget named `a` is printed
- [x] **Gate off, nothing is returned** (1)
  - Steps: same, with `w.set_gate(False)` before the list call
  - Expected: an empty list, no exception

Signed off by: fixture author, 2026-09-18.
