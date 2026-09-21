# AxiomaSkills

A personal marketplace of Claude Code plugins. One plugin per directory under
`plugins/`, served from this repo by relative path.

| Plugin | What it is |
|--------|-----------|
| [`agentic-workflow`](plugins/agentic-workflow/) | An opinionated way to build software with agents: you supply product judgment and manual testing, agents do the planning, coding, reviewing and bookkeeping. Nine skills and two reviewer agents. [Operator's manual](plugins/agentic-workflow/README.md) |
| [`writer`](plugins/writer/) | A single agent that writes, rewrites or summarises prose in a plain, peer-to-peer voice — evidence records, analysis notes, CV and cover-letter paragraphs, orientation summaries, correspondence. Reads a project's `writing-style.md` as an override. [Details](plugins/writer/README.md) |

Each plugin is versioned and installed **independently**. Adding one never
forces a version bump on the others.

## Install

```shell
claude plugin marketplace add AxiomaBot/AxiomaSkills
claude plugin install agentic-workflow@axioma-skills
```

Adding a marketplace enables nothing on its own — the install is always a
separate step. Add `--scope user` to make a plugin available in every repo on
the machine; the default records it against the current project instead.

**There is no commit pin.** A plugin entry's `source` can address a repo root
but not a subdirectory, so nothing can name `plugins/<name>` at a given commit;
pinning the marketplace instead does not work either, because a marketplace
source's `sha` is accepted and then never used. Serving several plugins from
one repo and pinning them are mutually exclusive, and this repo chose the
former.

In practice that costs little. A marketplace auto-updates only if you switch it
on, and that is off by default here, so an installed plugin does not change
until you update it. The drift that pinning never prevented is your own: a
clone loaded with `--plugin-dir`, or symlinked into `~/.claude/skills/`, is read
live. **So the rule is a habit, not a setting: do not edit a skill while a chunk
is in flight.** The plugin's own README has the
[longer version](plugins/agentic-workflow/README.md#there-is-no-commit-pin-and-why-that-is-acceptable).

This repo works as a private marketplace as long as the machine's git
credentials can clone it.

## Developing a plugin

```bash
claude --plugin-dir plugins/agentic-workflow                      # one
claude --plugin-dir plugins/agentic-workflow --plugin-dir plugins/other   # two
```

`--plugin-dir` names a directory holding `.claude-plugin/plugin.json`. It is
**repeatable**, one flag per plugin; it does not scan a folder for them. The
plugin loads for that session only, and `/reload-plugins` picks up edits
without a restart.

Run the checks from **this** directory, never from inside a plugin:

```bash
pytest -q
ruff check . && ruff format --check .
```

## Layout

```
.claude-plugin/marketplace.json   the index — lists every ./plugins/<name>
plugins/<name>/                   one plugin; everything here ships to consumers
  .claude-plugin/plugin.json      its own name, version and description
tests/                            covers the bundled scripts and this layout
fixture/                          a toy project for smoke-testing a skill change
scripts/                          this repo's own CI guards, dogfooded
```

The split is the rule worth keeping: **a plugin directory holds only what gets
installed.** Anything that exists to develop or test a plugin stays at the repo
root, because everything inside `plugins/<name>/` is copied to every consumer.

## Adding a plugin

1. Create `plugins/<name>/.claude-plugin/plugin.json` with `name`, `version`
   and `description`. The `name` must equal the directory name.
2. Add an entry to `.claude-plugin/marketplace.json` with
   `"source": "./plugins/<name>"`.
3. `pytest -q`. `tests/test_marketplace.py` checks both of the above, so a
   half-finished addition fails by name rather than shipping broken.

A plugin can bundle more than skills and agents — hooks, MCP servers, LSP
servers and output styles all load by directory convention, and `plugin.json`
can override any path.

## Releasing

Bump `version` in the changed plugin's own `.claude-plugin/plugin.json`. The
plugin cache is keyed by version, not by commit, so without a bump every
machine keeps serving the old content and `claude plugin update` reports there
is nothing to do. With no pin, that version is the only signal a consumer's
machine gets that anything changed, so a release without a bump silently does
not ship.
