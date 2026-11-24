# Manual tests — demo-widget

The checkpoint checklist for this feature, folded in one chunk at a time by
the `handoff` skill. Final-state assertions, not a per-chunk log, and only
what needs a person: the gate checks are automated.

> **When to run:** once every chunk is merged, one session at a time, in the
> order below.
>
> **Setup:** a shell in `fixture/` and any Python 3.10+.

## A demo caller sees the widget list, and only behind the gate

### Local, no credentials

- [ ] **The demo list shows only what a demo visitor should see** (1)
  - Steps: from `fixture/`, with nothing stored yet, run
    `python -c "import src.widgets as w; w.set_gate(True); w.set_demo(True); w.add_widget('kettle','ada'); w.add_widget('lamp','grace'); print(w.demo_list())"`
    and read the output as a visitor who owns neither widget.
  - Expected: you are content for that visitor to see every name and owner
    printed. Anything you would rather keep private is a failure.

Signed off by: <human, date>.
