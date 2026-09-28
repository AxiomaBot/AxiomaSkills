# AxiomaSkills — the `agentic-workflow` plugin

A Claude Code plugin that installs one opinionated way of building software
with agents: **you supply product judgment and manual testing; agents do the
planning, coding, reviewing and bookkeeping**, through nine skills that hand
work to each other through files in your repository.

This README is the **operator's manual**. It describes what *you* do at each
step and which skill to invoke. It is deliberately project-agnostic: every
command your project actually runs — lint, format, test — comes from your own
`CLAUDE.md` → `## Commands`, never from this plugin.

- The method itself lives in `skills/*/SKILL.md`. Those files are the
  contract; this README is how to drive them.
- The repo around this plugin carries `fixture/`, a toy project for
  smoke-testing a change to a skill. See
  [fixture/README.md](https://github.com/AxiomaBot/AxiomaSkills/blob/main/fixture/README.md).

---

## Read this first: every skill is namespaced

Claude Code **always** namespaces plugin skills by the plugin's `name` in
`.claude-plugin/plugin.json`. This plugin is named `agentic-workflow`, so
there is no bare `/plan` — it is `/agentic-workflow:plan`. This is not
configurable except by renaming the plugin.

The skill files' own prose says "the `plan` skill" or "`/build`" for
readability. When *you* type it, type the namespaced form:

| If you read | Type |
|-------------|------|
| `/workflow init\|check` | `/agentic-workflow:workflow init` · `/agentic-workflow:workflow check` |
| `/roadmap init\|detail\|refine` | `/agentic-workflow:roadmap init` · `… detail <feature>` · `… refine <change>` |
| `/plan <feature> <chunk>` | `/agentic-workflow:plan <feature> <chunk> [--auto]` |
| `/build <feature> <chunk>` | `/agentic-workflow:build <feature> <chunk>` |
| `/handoff <feature> <chunk>` | `/agentic-workflow:handoff <feature> <chunk>` |
| `/pr-review` | `/agentic-workflow:pr-review [PR#] [--model <m>]` |
| `/fix-review` | `/agentic-workflow:fix-review` |
| `/auto-chunk <feature> <chunk>` | `/agentic-workflow:auto-chunk <feature> <chunk>` |
| `/retro <feature>` | `/agentic-workflow:retro <feature>` |

Two things that are *not* namespaced and are worth keeping apart:

- **The bundled scripts.** Skills invoke them as
  `${CLAUDE_PLUGIN_ROOT}/skills/<name>/scripts/<script>.py` —
  `${CLAUDE_PLUGIN_ROOT}` is the plugin's own directory, wherever Claude Code
  installed it. Never copy a script into your project; run it from there.
- **The reviewer agents.** `agents/quality-reviewer.md` and
  `agents/security-reviewer.md` are spawned by the `pr-review` skill, not
  typed by you.

---

## The loop at a glance

```
roadmap.md                       direction + the feature index
docs/features/<slug>/feature.md  one feature: goal, decisions, chunks with
                                 specs, dependencies, dark-ship line, checkpoint
      │
      ▼
plan <feature> <chunk>           asks you everything, writes the chunk file
                                 docs/features/<slug>/chunks/<n>-<slug>.md
      │
      ▼
build <feature> <chunk>          implements unattended: code + tests
                                 + self-review + the project's verify step
      │
      ▼
handoff <feature> <chunk>        manual test steps → the feature's
                                 manual_tests.md; boxes ticked; status set
      │
      ▼
open the PR → pr-review          two fresh reviewer subagents on the diff:
                                 code quality + security → posted to the PR
      │
      ▼
fix-review (if blocking)         fix every blocking issue, push once,
                                 pr-review the new head; clean is a stop
      │
      ▼
squash-merge to main             main is always CI-green but NOT released
      │
      ▼  (once every chunk in a checkpoint's range is merged)
YOU: run the checklist           docs/features/<slug>/manual_tests.md
      │
      ▼
tag a release                    your project's release trigger, not a merge
      │
      ▼
retro <feature>                  measure it; expect "no change"
```

Three properties hold the whole thing together:

1. **Merging never releases.** Only your project's release trigger does — a
   version tag, a promotion branch, a manual deploy. That is what lets agents
   merge autonomously while you keep the ship/no-ship decision.
2. **Every chunk merges dark.** A feature is invisible to users until you sign
   its checkpoint off. The feature file's `dark-ship` line names the
   **server-side** enforcement point — a config gate, a route guard, an opt-in
   checked in the service layer. UI concealment does not qualify, and the
   layout check rejects a line that names only a template or a nav change.
3. **Features run in parallel on trunk.** Each feature owns its own folder, so
   two features touch disjoint files. Dependencies are *declared*
   (`depends-on: <feature>/<chunk>`), never stacked as branches, and the
   `plan` skill refuses to start until a dependency is on `main`.

---

## Installation

### Requirements

- Claude Code with plugin support.
- Python 3.10+ on `PATH` for the bundled scripts — the two the skills run
  (`workflow_check.py`, `review_context.py`) and the CI guard
  `check_committed_permission_grants.py`. Standard library only, nothing to
  install. A project with a managed environment prefixes the skills' scripts
  the way its own `CLAUDE.md` → Commands does (`poetry run`, `uv run`, …);
  the CI guard runs on the GitHub runner's `python3`.
- `git`, and `gh` or equivalent for the skills that open PRs and post review
  comments.

### Local development of the plugin itself (verified)

```bash
claude --plugin-dir /path/to/AxiomaSkills/plugins/agentic-workflow
```

`--plugin-dir` names the directory holding `.claude-plugin/plugin.json`, which
since this repo went multi-plugin is the plugin's own folder, not the repo
root. The flag is **repeatable**, so a second plugin is a second `--plugin-dir`;
it does not scan a folder for plugins.

The plugin loads for that session only, and `/reload-plugins` picks up edits
without a restart. This is the path to use when you are changing a skill and
smoke-testing it against the repo's `fixture/`.

### Consuming project

```shell
claude plugin marketplace add AxiomaBot/AxiomaSkills
claude plugin install agentic-workflow@axioma-skills
```

The install defaults to user scope, which makes it available in every repo
on the machine; add `--scope project` to record it against the current repo
instead. Adding a marketplace enables
nothing on its own — the install is always a separate step. A private
repository works as a marketplace as long as the machine's git credentials can
clone it.

### Cloud sessions (claude.ai/code, the mobile app, cloud sessions in Claude Desktop)

**Neither a CLI install nor the repo's settings reach a cloud session.** A
cloud session runs in a fresh container: a new home directory, so nothing from
your machine's `~/.claude`. It also skips the `extraKnownMarketplaces` and
`enabledPlugins` a repo commits in `.claude/settings.json`, because adding a
marketplace from repo settings waits for the workspace-trust prompt, and a
cloud session never shows one. It skips them silently: the only symptom is
`claude plugin marketplace list` printing `No marketplaces configured`. See
[plugin loading](https://code.claude.com/docs/en/plugins/loading#plugins-shared-through-a-repository)
and
[what carries over to a cloud session](https://code.claude.com/docs/en/cloud-environments#what-carries-over-from-your-setup).

Two routes do work:

1. **The cloud environment's setup script** (any plan). Put the install in the
   environment's setup script, under the environment menu in the session's
   title bar, then **Edit**:

   ```bash
   claude plugin marketplace add AxiomaBot/AxiomaSkills
   claude plugin install agentic-workflow@axioma-skills
   claude plugin install writer@axioma-skills
   ```

   The script runs before Claude Code starts, so the session loads the
   plugins at startup. It applies to every repo that uses the environment,
   not to one repo. Its output is cached, and the script re-runs only when you
   edit it, change the network settings, or the cache expires after about a
   week. So a new plugin version reaches cloud sessions at the next re-run,
   not at the next push. The environment's network access has to reach
   github.com.

   *Tested:* running these three commands inside a cloud container, then
   starting Claude Code, loaded both plugins, all nine skills and all three
   agents. *Not tested:* the same commands as an actual setup script.

2. **Organization managed settings** (Team or Enterprise, Owner role). Put
   the same two keys as the snippet below in
   [claude.ai/admin-settings/claude-code](https://claude.ai/admin-settings/claude-code).
   A cloud session fetches those settings before it installs plugins
   ([docs](https://code.claude.com/docs/en/plugins/org#choose-a-delivery-mechanism)).
   They apply to every member of the organization, in every repo.

### Local sessions: commit the plugins to the consuming repo

For local sessions (the CLI, or local sessions in Claude Desktop or an IDE), a
consuming repo can carry the plugins in its own `.claude/settings.json`
instead of each machine installing them:

```json
{
  "extraKnownMarketplaces": {
    "axioma-skills": {
      "source": { "source": "github", "repo": "AxiomaBot/AxiomaSkills" }
    }
  },
  "enabledPlugins": {
    "agentic-workflow@axioma-skills": true,
    "writer@axioma-skills": true
  }
}
```

The marketplace key must be `axioma-skills`, the `name` in this repo's
`marketplace.json`, because that is what the `@axioma-skills` suffix resolves
against. List only the plugins the project uses. Neither key is a permission
grant, so the committed-grant guard lets the file through.

The marketplace is added after you accept the workspace-trust prompt for that
folder. Because this marketplace serves its plugins by relative path, they
then load with no separate install. This file does nothing in a cloud session.

#### There is no commit pin, and why that is acceptable

This plugin used to sit at its repo's root and a consuming project could pin it
to a **commit SHA** through its own marketplace file, so that a skill edit
never changed a build mid-feature. **That is no longer available**, and the
reason is structural rather than an oversight:

- A plugin entry's `source` accepts `npm`, `github`, `url` or a local path.
  `github` takes `repo`, `ref` and `sha` — and **no** subdirectory field, so it
  can only ever address a repo *root*. After a fetch, Claude Code looks for
  `.claude-plugin/plugin.json` at the root of what it cloned.
- This plugin lives in `plugins/agentic-workflow/`, so no plugin entry can name
  it. Pinning the *marketplace* instead does not help: a marketplace source's
  `sha` is accepted by the schema and then never passed to the clone, which is
  the first trap below.

So the choice was one pinnable plugin per repo, or several plugins per repo and
no pin. This repo chose the second. What actually replaces the pin:

1. **Nothing drifts on its own.** A marketplace auto-updates only if you switch
   it on, and the default is off for every marketplace outside Anthropic's own
   list. Until you run `claude plugin marketplace update` and
   `claude plugin update`, the installed copy is the one you installed. That is
   most of what a pin bought.
2. **The real drift risk is your own editing**, not the marketplace. A clone
   symlinked into `~/.claude/skills/`, or loaded with `--plugin-dir`, is read
   live: save a skill file and the next session has it. Pinning never protected
   against that, because both routes bypass the marketplace entirely.
3. **So the rule that matters is a habit:** do not edit a skill while a chunk is
   in flight. Land the plugin change, then start the next chunk.

What you give up by having no pin is **reproducibility, not safety**: you can no
longer say for certain which version of the method produced a given PR. A retro
reading rounds across a feature is the one thing that depends on it, so if a
feature spanned a plugin change, say so in the retro rather than trusting the
count.

> **Two traps.** Neither reports an error. The first was found by pinning
> this for real; both were later confirmed against the CLI itself, which is
> the only way to be sure of either.
>
> 1. **`sha` on a marketplace's own source is accepted and then ignored.**
>    The schema takes the field, so nothing complains. The marketplace fetch
>    passes only `ref` to the clone and drops `sha` on the floor, so
>    `claude plugin marketplace update` prints "Successfully updated" and
>    checks out the branch tip regardless. A project that puts a `sha` there
>    believes it is pinned and is not. Only a *plugin entry's* source honours
>    `sha` — and that route cannot address a plugin in a subdirectory, which
>    together is why this plugin has no pin at all.
> 2. **The plugin cache is keyed by `version`, not by commit.** Change the
>    content without touching `version` and every machine keeps serving the
>    old copy, while `claude plugin update` answers "already at the latest
>    version (x.y.z)" and does nothing. **So every release bumps `version` in
>    that plugin's own `.claude-plugin/plugin.json`** — the file inside
>    `plugins/<name>/`, which is per plugin, so a change to one never forces a
>    version on the others. Without a pin this is the *only* thing telling a
>    consumer's machine that anything changed, so skipping it is not a
>    cosmetic slip: it is a release that silently does not ship.

`enabledPlugins` and `extraKnownMarketplaces` are ordinary settings, not
permission grants — and note that this workflow treats a committed
permission grant as a defect: an `allow` entry, an `additionalDirectories`
entry, a `defaultMode` that is not `default` or `plan`, or either of the
MCP auto-approvals, `enableAllProjectMcpServers` and `enabledMcpjsonServers`.
Both this repo and every project the `workflow` skill scaffolds run a CI guard
that fails a PR whose tree carries one; a tool grant your orchestration needs
belongs in untracked local settings.

The rule is **absolute, not differential**: the guard looks at the PR's own
tree and fails if a grant is there at all. It does not diff against the base,
so there is nothing to grandfather in — a grant that predates the workflow
fails the next PR that touches the repo, and no sequence of commits can walk
one past it. That also means it has no override: a grant has no legitimate
in-repo form, so there is no case to let through.

Restrictions (`deny`, `ask`, `disableBypassPermissionsMode`,
`disabledMcpjsonServers`) are deliberately **not** watched. Tracking whether
one was weakened means reconstructing the base tree and modelling rule
ordering and scope ancestry — most of the guard's complexity for the case a
human reviewer reads most easily, since deleting a `deny` line is visible in
the diff. The guard keeps the case a reviewer misses: a grant buried in a
settings file they did not open.

It reads **every** tracked `.claude/settings*.json` at any depth, since
`packages/app/.claude/settings.json` is live for anyone working in that
subdirectory, and it enumerates paths as raw bytes from the repo root so
neither a non-ASCII directory name nor an odd working directory can hide one.
On a sparse checkout it falls back to the file's content in the index.

And it **fails closed**: a settings file it cannot read or parse — empty,
malformed, undecodable bytes, or a JSON shape it did not expect — is an error
rather than a pass, because a control that reports success on input it could
not read is worse than no control at all.

---

## First run in a new project

```shell
# install the plugin (above), then, in the project:
/agentic-workflow:workflow init
/agentic-workflow:workflow check
```

`init` is **attended** — the direction paragraph and the feature list are your
judgment, and it stops if there is nobody to ask. It handles both a fresh
project and a migration from an older shape (one plan file, one test
checklist, one deferred log): superseded files move to `docs/archive/`
verbatim, closed phases compress to one row each under `## Done`, and the
phase in flight becomes the first feature folder.

What you end up with:

```
CLAUDE.md                      # ## Commands + ## Models (+ your own content)
AGENTS.md                      # ## Domain rules for code review,
                               #   ## Release model, ## Weak spots
roadmap.md                     # direction, the feature index, done, backlog
docs/
  features/<slug>/
    feature.md                 # goal, decisions, chunks with specs,
                               #   depends-on, dark-ship, checkpoint
    chunks/<n>-<slug>.md       # one build contract per chunk
    manual_tests.md            # this feature's checkpoint checklist
  retros/<slug>.md             # one per feature
  deferred.md                  # actionable only
  weak-spots.md                # capped at 30; only the retro skill writes it
  roadmap_changelog.md
.github/workflows/pr-guards.yml
scripts/check_committed_permission_grants.py
scripts/check_review_coverage.sh
```

`check` runs `skills/workflow/scripts/workflow_check.py` and writes nothing.
Exit 0 means every structural rule held; otherwise each finding is one
`<file>: <what>` line. It is a check on the layout and on the *shape* of what
the files claim — a `dark-ship` line passes because it names a non-UI code
reference, not because anything confirmed that gate exists, is reached on
every path, or defaults off. Read a clean run as "nothing structural is
missing", never as evidence that a control holds.

Once `check` passes, cut the first feature into chunks and run one:

```shell
/agentic-workflow:roadmap detail <feature>
/agentic-workflow:auto-chunk <feature> <chunk>
```

---

## Your jobs (everything else is the agents')

1. **Decide what to build** — keep `roadmap.md` honest. `roadmap detail` turns
   the next outlined feature into `docs/features/<slug>/feature.md` with
   PR-sized chunks.
2. **Answer questions at plan time** (attended), or **skim the recorded
   assumptions afterwards** (`--auto`).
3. **Respond to escalations** — the autonomous pipeline stops and asks you at a
   genuine product decision, a disputed review finding, or an infrastructure or
   quota failure. It never grinds past a blocker.
4. **Run the manual-test checklist** in `docs/features/<slug>/manual_tests.md`
   when a checkpoint is reached — once per checkpoint, not per chunk.
5. **Sign off and release**: mark the feature `done` in `feature.md` and
   `roadmap.md`, then trigger your project's release the way `AGENTS.md` →
   Release model describes.

---

## Two ways to run a chunk

### Autonomous — `auto-chunk` (the default when every decision has a safe default)

```shell
/agentic-workflow:auto-chunk <feature> <chunk>
```

One command; you only initialize and manual-test later. It spawns the planner
on the planning model (resolving every fork with a recorded assumption), the
builder on the chunk file's `Build model:`, runs the handoff, opens the PR,
runs the reviews, fixes blocking issues round by round on the fix-review model
— re-reviewing after each push — and squash-merges. It **escalates to you**
instead of guessing when the plan hits a product decision with no safe
default, when a reviewer fails to produce a verdict even after a re-spawn (an
ops problem, never a PASS), when a blocker is disputed on evidence, or when
rounds pass without converging. It never tags a release.

### Attended — step by step (when the chunk has real product decisions)

| Step | Skill | Tier | Mode | You do |
|------|-------|------|------|--------|
| 1 | `plan <feature> <chunk>` | planning | normal | Answer every clarifying question |
| 2 | `build <feature> <chunk>` | the chunk's `Build model:` | auto-accept | Nothing — it hands off, opens the PR and runs the reviews |
| 3 | `fix-review` | fix-review | normal | If a review blocks — **or flags anything security-relevant, even on an otherwise-clean head**: review the edits, commit and push them yourself (the fix skill never commits), then re-run `pr-review` on the new head |
| 4 | Squash-merge | — | — | Once both reviews are clean for the head and CI is green |
| 5 | Manual test at the checkpoint, sign off, release | — | — | Run the checklist, mark `done`, tag |

You toggle auto-accept yourself before `build`.

---

## The nine skills

Tiers are floors, not pins: a skill runs on your session's model as long as it
is at or above its tier's floor, stops rather than run below it, and never
switches your session down.

| Skill | Tier | What it does | Writes |
|-------|------|--------------|--------|
| `workflow init\|check` | coding | Scaffold or migrate a project into the per-feature workflow layout (`init`), or verify it (`check`) — the layout, the `AGENTS.md`/`CLAUDE.md` sections, the model floors, and every `depends-on` entry | `init`: the skeleton above. `check`: nothing |
| `roadmap init\|detail\|refine` | planning | Plan-stage skill — create the roadmap, detail one feature into chunks with specs, or fold a change in as a diff. **Attended only.** | `roadmap.md`, `docs/features/<slug>/feature.md`, and — `refine` only — a dated line in `docs/roadmap_changelog.md` |
| `plan <feature> <chunk> [--auto]` | planning | Plan one chunk — resolve every question, derive its invariants, write the build contract. Refuses until every `depends-on` chunk is on `main`, verifies every claim it makes about existing code, and picks the build model | `docs/features/<slug>/chunks/<n>-<slug>.md` |
| `build <feature> <chunk>` | coding, raised to the chunk's `Build model:` | Build one planned chunk unattended — implement its chunk file with tests, self-review, verify, hand off, open the PR and review it. Refuses on a `[?]` marker or a session below the chunk's model | code, tests, `docs/deferred.md` for out-of-scope finds |
| `handoff <feature> <chunk>` | coding | Pre-PR bookkeeping for a built chunk — fold its manual test steps into the feature's checklist, tick its boxes, set the feature status, update the `roadmap.md` index row. Never the checkpoint boxes, never `done` | `manual_tests.md`, `feature.md`, the `roadmap.md` row |
| `pr-review [PR#] [--model <m>]` | coding (spawns the review tiers) | Run both PR reviews (code quality + security) as fresh, diff-only subagents on the PR head, post their reports, and report the verdicts. Run after opening a PR and after **every** push | PR comments only |
| `fix-review` | fix-review | Address both PR reviews — self-fetches the quality report and the security verdict for the current head — fix every blocking issue with a sibling sweep, and file or escalate every security-relevant finding even on an otherwise-clean head. Disagrees only with file-and-line evidence | code, tests, `docs/deferred.md` |
| `auto-chunk <feature> <chunk>` | coding (spawns the rest) | Run one chunk end to end unattended — plan → build → handoff → PR → review loop → squash-merge. You only initialize and manual-test | everything above |
| `retro <feature>` | planning | Feature close — measure how a completed feature actually went, default to "no change", propose at most three workflow edits, each naming what it replaces. **The only writer of `docs/weak-spots.md`** | `docs/retros/<slug>.md`, `docs/weak-spots.md` |

Harness skills the workflow leans on but does not ship: a code-review skill
for the pre-PR self-review, and your project's own end-to-end verify skill if
it has one (`build` uses it when present and says so when it is not).

### The two reviewer agents

`pr-review` never reviews in its own voice — it holds the author's context, so
its own reading is not independent. Instead it:

1. builds a compact diff context with
   `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/scripts/review_context.py`
   (`changed-files.txt` + `pr.diff`, budgeted per variant, with process
   artifacts such as chunk files listed but withheld from the diff);
2. spawns `quality-reviewer` and `security-reviewer` **in parallel, in one
   message**, each with only its variant's file paths and the PR number — no
   summary of intent, no plan excerpts, no defence of decisions;
3. posts each report verbatim as its own PR comment, with
   `Reviewed head: <sha>` and `Reviewed by: <model>` inserted under the H1.

Both agents read these, and nothing else: the diff context, `AGENTS.md` →
Domain rules for code review and Release model, and `docs/weak-spots.md`.
Their report headers — `# Code quality review` and `# Security review
verdict` — are a machine contract read by `fix-review`, by `retro`, and by the
`review-coverage` job in `pr-guards.yml`. Change a header and you sweep all
three.

Neither agent file pins a `model:`. Passing the model is `pr-review`'s job,
from the tier table in your `CLAUDE.md`; if it cannot set the model
explicitly it reports that instead of spawning on the session's model. A
security review that quietly ran below its floor is the failure that rule
exists to prevent.

---

## The documents

| File | What it is | Who writes it | When you read it |
|------|-----------|---------------|------------------|
| `roadmap.md` | Direction, the feature index with statuses, outlined features, the backlog | You + `roadmap`; `handoff` (a feature's row); you (marking `done`) | When deciding what's next |
| `docs/features/<slug>/feature.md` | One feature: goal, milestone, settled decisions, chunks with spec blocks, `depends-on`, `dark-ship`, checkpoint | `roadmap detail`; `handoff` (boxes + status); you (`done`, sign-off) | When starting or reviewing a feature |
| `docs/features/<slug>/chunks/<n>-<slug>.md` | One chunk's build contract: invariants, decisions or assumptions, tasks, manual test steps, `Build model:` | `plan` | Skim the assumptions after an `--auto` plan |
| `docs/features/<slug>/manual_tests.md` | That feature's checkpoint checklist | `handoff` | At the checkpoint — your main job |
| `docs/weak-spots.md` | The repo's recurring classes of mistake, capped at 30 | `retro`, and nothing else | Rarely — `build` and both reviewers read it for you |
| `docs/deferred.md` | Parked bugs, cleanups, tests — **actionable only** | `build`, `fix-review` | Rarely — `plan` offers the relevant entries back |
| `docs/roadmap_changelog.md` | Dated one-liners for every roadmap refinement | `roadmap refine` | When asking "why did the plan change?" |
| `docs/retros/` | Per-feature retro reports | `retro` | At feature close — approve or reject its proposals |
| `AGENTS.md` | Domain rules, release model, weak-spots pointer — the agents' contract | You (rarely) | When the rules of the game change |
| `CLAUDE.md` | `## Commands` and `## Models`, plus whatever else your project keeps there | You | When the toolchain or the model policy changes |

Feature statuses, in order: `idea` → `outlined` (both live in `roadmap.md`
only) → `planned` (folder exists) → `building` → `built` (all chunks merged,
checkpoint pending) → `done` (checkpoint signed off). `roadmap detail` is what
moves a feature from `outlined` to `planned` and creates its folder.

### Writing good chunks: the spec block

Autonomous builds are only as good as the judgment written into the plan. Each
chunk in `feature.md` carries a spec block:

- **Invariants** — what must stay true, including what must be *refused*; the
  negative-test targets the build satisfies *before* review. An invariant
  stated here costs nothing; one left unstated is what the reviewers find, one
  round at a time.
- **Decisions** — which forks the agent may auto-pick, and which it must ask
  you about first.
- **Depends-on / must-not-break** — prior chunks, files and invariants it
  builds on.
- **Verify** — the one runtime behaviour the verify step must exercise.
- **Build model** — optional; set when the reason is already known.

Front-loading these is the single highest-leverage thing you do here.

---

## Templates, and what `workflow init` does with each

Everything in `templates/` is a starting point that `init` copies into *your*
repository. Nothing is read back from the plugin at run time, and nothing in
your project is ever regenerated from here.

| Template | Where it lands | Notes |
|----------|----------------|-------|
| `templates/roadmap.md` | `roadmap.md` | Direction, Features, Done, Backlog — the four sections `check` requires |
| `templates/weak-spots.md` | `docs/weak-spots.md` | Header, the expiry rule, the tag vocabulary, an empty five-column table. On a migration, seeded one line per recurring-blocker category from your old build prompt, anecdotes dropped |
| `templates/feature.md` | `docs/features/<slug>/feature.md` | Written by `roadmap detail` per feature, not by `init` itself |
| `templates/chunk.md` | `docs/features/<slug>/chunks/<n>-<slug>.md` | Written by `plan` per chunk |
| `templates/models.md` | `CLAUDE.md` → `## Models` | The tier table, floors and "go one up" triggers. **The only copy** — the skills and this README point here rather than restating it |
| `templates/agents-sections.md` | appended to `AGENTS.md` | The three `##` headings read *by name* by the skills and both reviewer agents: Domain rules for code review, Release model, Weak spots. Most of the content is yours and grows over time, except `## Weak spots` in full and `## Release model`'s four floor bullets, which are fixed by the method — `tests/test_bundled_copies.py` pins `fixture/AGENTS.md`'s copy of those to this template |
| `templates/pr-guards.yml` | `.github/workflows/pr-guards.yml` | All three jobs, not just one: a gitleaks secret scan on the PR's own commits, the committed-permission-grant guard, and review coverage |
| `templates/check_committed_permission_grants.py` | `scripts/` (run as `python3`) | Fails a PR whose tree contains **any** permission grant, in any tracked `.claude/settings*.json` at any depth: `allow`, `additionalDirectories`, a `defaultMode` other than `default`/`plan`, `enableAllProjectMcpServers`, or `enabledMcpjsonServers`. No base comparison — a grant that predates the workflow fails too, so there is nothing to grandfather in. Fails closed on a file it cannot read or parse. Stdlib-only, no `jq` |
| `templates/check_review_coverage.sh` | `scripts/` (executable) | Fails a PR whose head has not had both review reports posted |

`init` also writes, with no template: `CLAUDE.md` → `## Commands` (your
project's own lint, format and test commands), plus
`docs/deferred.md`, `docs/roadmap_changelog.md`, and `docs/features/` and
`docs/retros/` with a `.keep` in each, because git carries files, not
directories.

`pr-guards.yml` and its two scripts are **committed to your project and never
regenerated from the plugin**: GitHub Actions runs against your checkout, not
this one, and that deterministic floor is what sits under everything the
agents do.

### Upgrading the guard from 0.3.0 or earlier

0.3.0 and earlier shipped the permission guard as
`check_committed_permission_grants.sh`, a base-vs-head diff. 0.4.0 replaces
it with the absolute `.py` check. Because the guard lives in your project,
upgrading the plugin does not move it — do it by hand, in three steps:

1. `git rm scripts/check_committed_permission_grants.sh`
2. Copy `${CLAUDE_PLUGIN_ROOT}/templates/check_committed_permission_grants.py`
   to `scripts/check_committed_permission_grants.py`.
3. In `.github/workflows/pr-guards.yml`, replace the
   `no-committed-permission-grants` job's steps with the ones in
   [`templates/pr-guards.yml`](templates/pr-guards.yml): a plain
   `actions/checkout@v7` (no `fetch-depth: 0`), no jq step, no `BASE_SHA`
   env, and `run: python3 scripts/check_committed_permission_grants.py`.

**Do not re-run `workflow init` for this.** `init` is not idempotent — it
rewrites `roadmap.md`, `docs/weak-spots.md` and your `## Models` table from
the templates, discarding a running project's plan.

Expect the first PR after the swap to fail if a grant is already committed:
the new check is absolute, so it reports what the old differential one had
grandfathered in. That finding is real — move the grant to untracked local
settings.

---

## Model tiers and floors

`init` writes [`templates/models.md`](templates/models.md) into your
project's `CLAUDE.md` under `## Models`. **That file is the single source for
the tier table, and it is deliberately not reproduced here** — three hand-kept
copies of it is exactly how a floor drifts from the method. Read it there.

The **floors are the method**; the *Recommended* column and the *Go one up
when* triggers are yours to tune once the table lands in your project.

> The tier *names* in that table's left column are also parsed by
> `skills/workflow/scripts/workflow_check.py` (`TIERS`), and the repo's
> `fixture/` ships the table untuned as a real project would receive it. The
> repo pins both to the template in CI, so renaming a tier is one edit plus
> whatever CI then names — not a change you have to remember to make in three
> places.

Who picks, and where it is recorded:

- **The planner picks the build model.** `plan` ends the chunk file with
  `Build model: <model> — <why>`, defaulting to the coding recommendation and
  raising it on that table's *Go one up when* triggers. `build` reads it and stops if the session
  is below it; `auto-chunk` spawns the builder on it. `roadmap detail` may
  pre-set it in a chunk's spec when the reason is already known.
- **The session picks the planning model.** Running `plan` or `roadmap` on a
  stronger model needs no flag; the floor check only refuses a session that is
  too low.
- **`pr-review --model <m>`** raises both reviewers for that run, if `<m>` is
  at or above each floor. A chunk file may request it with a
  `Review model: <model> — <why>` line, and `auto-chunk` passes it through.

---

## Reviews, merging, releasing

- Every PR head gets **two** reviews — code quality and security — run
  in-session by `pr-review` as fresh, diff-only subagents; the reports are PR
  comments anchored to the head SHA. Nothing on GitHub triggers them: whoever
  pushes a head reviews it, and an unreviewed head is unreviewed, not passed.
  The reviews are **advisory** — the agent (or you) is the merge gate. The one
  **mechanical** gate is `pr-guards.yml`, and a red run there is honoured, not
  weighed.
- Agents may **disagree** with a finding, but only with concrete evidence
  (file and line, the existing guard, the covering test). Disputed findings are
  escalated to you, never silently merged over.
- **A clean head is a stop.** Non-blocking findings stay in the PR thread;
  nobody opens a push to file them. There is no harvest step anywhere
  downstream. The one carve-out: a security-relevant observation, or a "needs
  broader manual review" item, is `fix-review`'s to verify, fix, file to
  `docs/deferred.md`, or escalate before merge — so one of those is what makes
  a head *not* clean, and is worth a `fix-review` run on its own. **Nothing
  else drains them.**
- **Branching:** trunk-based. Every chunk is its own branch and PR into `main`;
  no long-lived development branch, and normally no feature branches — features
  ship dark behind their `dark-ship` gate instead. The one carve-out: a feature
  that genuinely cannot ship dark may use a branch, and only one such feature
  may be in flight at a time.
- **Releasing** is your project's own mechanism, described in `AGENTS.md` →
  Release model, and it is the one thing the agents never do. Release only
  after a checkpoint is signed off.

---

## Quick recipes

- **Start the next chunk:** `/agentic-workflow:auto-chunk <feature> <chunk>` —
  or `/agentic-workflow:plan <feature> <chunk>` if you want to be asked the
  questions.
- **A feature is about to start and is only an outline:**
  `/agentic-workflow:roadmap detail <feature>` — cuts it into chunks with spec
  blocks against the code as it exists *now*.
- **A feature just closed, or the goal moved:**
  `/agentic-workflow:retro <feature>` once the checkpoint is signed off, then
  `/agentic-workflow:roadmap refine <change>`. Expect "no change": retro
  proposals are capped at three and each has to name what it replaces, so
  approving one is a small PR of its own.
- **A PR head has no review yet, or a new push needs one:**
  `/agentic-workflow:pr-review` — then `/agentic-workflow:fix-review` if
  either review blocks, **or flags anything security-relevant, or leaves a
  "needs broader manual review" item**, even when nothing blocks. That last
  case is the whole drain: skip it and the finding lives only in the PR thread.
- **Something looks off in the layout or the docs:**
  `/agentic-workflow:workflow check`.
- **Checkpoint reached:** run `docs/features/<slug>/manual_tests.md` top to
  bottom, and report failures by item title or chunk tag.
- **You spot a bug mid-anything:** don't chase it — ask for it to be appended
  to `docs/deferred.md`; `plan` offers it back at the right chunk.

---

## Changing a skill

The skill files *are* the method, so treat an edit to one as a change to a
contract rather than to prose:

1. Make the edit.
2. Run the tests **from the repo root**, not from here: `pytest` (needs only
   pytest — both bundled scripts are stdlib-only). They cover the two scripts
   the skills execute, and one of them runs the layout check against
   `fixture/`, so a break in either the checker or the fixture fails here. A
   third pins the guard script the repo runs from `scripts/` byte-for-byte
   against the copy `init` ships from this plugin's `templates/`, so editing
   one and not the other fails rather than silently handing consumers a
   different guard. A fourth checks the `plugins/` layout itself. CI runs the
   same thing on every PR.
3. Run the skill you changed against `fixture/` in a session started with
   `claude --plugin-dir /path/to/AxiomaSkills/plugins/agentic-workflow`. See
   [fixture/README.md](https://github.com/AxiomaBot/AxiomaSkills/blob/main/fixture/README.md).
4. A rule that turns out to be wrong is a change to the script or the skill
   that owns it, in its own PR — never a workaround in the file it checks.
5. **Bump `version` in this plugin's `.claude-plugin/plugin.json`.** With no
   commit pin, that version is the *only* signal a consumer's machine gets
   that anything changed: the cache is keyed by it, so skipping the bump
   leaves every machine running the old content while `claude plugin update`
   reports there is nothing to do.
