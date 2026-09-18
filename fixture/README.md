# `fixture/` — a toy project for smoke-testing a skill change

`demo-shop` is not a real project. It is the smallest repository that still
satisfies every rule the `workflow` skill's `check` mode enforces: two
features (`demo-foundation`, closed; `demo-widget`, mid-flight), one chunk
with a build contract, one dependency edge between features, one real
dark-ship gate, and lint/format/test commands that are stubs which always
exit 0. Nothing here needs a language toolchain — the point is to exercise
the *workflow* skills, not a build.

## Smoke-test a skill change

**1. The layout check, from the plugin repo root:**

```bash
python skills/workflow/scripts/workflow_check.py --root fixture
```

Exit 0 and `workflow check: OK` is the expected result on a clean checkout.
The script is standard library only, so any Python 3.10+ will run it; a
consuming project prefixes it with whatever its own `CLAUDE.md` → Commands
uses to run Python (`poetry run`, `uv run`, or nothing).

**2. The skill you actually changed.** Open a Claude Code session with its
working directory set to `fixture/` and this plugin loaded — during
development that is `claude --plugin-dir /path/to/AxiomaSkills` — then invoke
the skill by its namespaced name and watch what it writes:

```shell
/agentic-workflow:workflow check
/agentic-workflow:plan demo-widget 1
/agentic-workflow:build demo-widget 1
```

`demo-widget`'s chunk 1 is deliberately planned but **not built**:
`src/widgets.py` carries the store and its gate, and ends with a comment
marking where `demo_enabled`, `set_demo` and `demo_list` go. That is the hole
a `plan`/`build` smoke test fills.

## Putting it back

The fixture is meant to be dirtied. After a run, throw the changes away:

```bash
git checkout -- fixture && git clean -fd fixture
```

If a skill change means the fixture *should* now look different — a new
required section, a new file the layout expects — that edit belongs in the
same PR as the skill change, and `workflow_check.py --root fixture` has to go
back to exit 0 before it merges.
