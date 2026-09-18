# Manual tests — demo-widget

The checkpoint checklist for this feature, folded in one chunk at a time by
the `handoff` skill. Final-state assertions, not a per-chunk log. Run it top
to bottom once every chunk is merged.

## A demo caller sees the widget list, and only behind the gate

- [ ] **Both gates on, the demo list shows the widgets** (1)
  - Steps: `python -c "import src.widgets as w; w.set_gate(True); w.set_demo(True); w.add_widget('a','ada'); print(w.demo_list())"`
  - Expected: one widget named `a` is printed
- [ ] **Demo gate off, the demo list is empty** (1)
  - Steps: same, with `w.set_demo(False)`
  - Expected: an empty list, even though the store gate is on

Signed off by: <human, date>.
