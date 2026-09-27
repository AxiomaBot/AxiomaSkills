"""Tests for the layout check behind the `workflow` skill's `check` mode.

Each test builds the smallest project that passes, breaks exactly one rule,
and asserts the one finding that names it. The passing fixture is the
contract every skill in this plugin reads against.

These moved here from the first project to consume the plugin, where they ran
against that repo's own copy of the script. The copy under test is now the one
the skill actually runs -- which is the point of moving them.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "agentic-workflow"
SCRIPT = PLUGIN / "skills" / "workflow" / "scripts" / "workflow_check.py"
FIXTURE = REPO / "fixture"


def _load():
    """Import the script by path -- scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("workflow_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


wc = _load()

MODELS = """\
## Commands

```bash
poetry run pytest
```

## Models

Order, weakest first: haiku < sonnet < opus < fable (extend when one ships).

| Tier | Floor | Recommended | Go one up when |
|------|-------|-------------|----------------|
| planning | opus | opus | — |
| coding | sonnet | sonnet | — |
| fix-review | sonnet | opus | — |
| quality review | sonnet | sonnet | — |
| security review | opus | opus | — |
"""

AGENTS = """\
# AGENTS

## Domain Rules for Code Review
- rule

## Release model
- tags

## Weak spots
See `docs/weak-spots.md`.
"""

ROADMAP = """\
# Roadmap

## Direction
Somewhere.

## Features
| Feature | Status | One line |
|---------|--------|----------|
| [alpha](docs/features/alpha/feature.md) | building | First |
| beta | outlined | Second |

## Done
| Feature | Shipped | One line |
|---|---|---|

## Backlog
- nothing
"""

FEATURE = """\
---
status: building
depends-on: []
dark-ship: "`competitions.api_enabled`, checked in `shared/services/gate.py`"
checkpoint: It works
---
# Feature: Alpha

## Goal
## Chunks
### 1 — First chunk
- [x] task
### 2 — Second chunk
- [ ] task

## Test checkpoint
- [ ] check
"""

WEAK_SPOTS = """\
# Weak spots

| Class | Tag | What to check | Added | Last fired |
|-------|-----|---------------|-------|------------|
| Thing | security | Check it | W1 | W1 |
"""


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    _write(tmp_path, "CLAUDE.md", MODELS)
    _write(tmp_path, "AGENTS.md", AGENTS)
    _write(tmp_path, "roadmap.md", ROADMAP)
    _write(tmp_path, "docs/deferred.md", "# Deferred\n")
    _write(tmp_path, "docs/weak-spots.md", WEAK_SPOTS)
    _write(tmp_path, "docs/retros/.keep", "")
    _write(tmp_path, "docs/features/alpha/feature.md", FEATURE)
    _write(tmp_path, "docs/features/alpha/manual_tests.md", "# Manual tests\n")
    return tmp_path


def _findings(root: Path) -> list[str]:
    return wc.run(root).findings


# --- the passing fixture and the bundled fixture project ------------------------


def test_minimal_project_passes(project: Path):
    assert _findings(project) == []


def test_the_bundled_fixture_passes():
    """The shipped `fixture/` project is a fixture for this test, deliberately.

    `fixture/` exists so a skill change can be smoke-tested against a real
    layout, and this is what keeps it honest: a change that breaks the layout
    contract -- in the checker or in the fixture -- fails CI rather than
    waiting for someone to run the skill and notice. The cost is that a PR
    editing `fixture/` can fail *this* test for a layout reason with no other
    signal; read the finding it prints, which names the file and the rule.
    """
    assert _findings(FIXTURE) == []


def test_cli_exit_status(project: Path, capsys):
    assert wc.main(["--root", str(project)]) == 0
    assert "OK" in capsys.readouterr().out
    (project / "roadmap.md").unlink()
    assert wc.main(["--root", str(project)]) == 1
    assert "roadmap.md: missing" in capsys.readouterr().out


# --- layout and sections -------------------------------------------------------


@pytest.mark.parametrize("rel", wc.REQUIRED_PATHS)
def test_each_required_path_is_reported_when_missing(project: Path, rel: str):
    target = project / rel
    if target.is_dir():
        for child in target.rglob("*"):
            if child.is_file():
                child.unlink()
        for child in sorted(target.rglob("*"), reverse=True):
            child.rmdir()
        target.rmdir()
    else:
        target.unlink()
    assert f"{rel}: missing" in _findings(project)


def test_agents_sections_are_matched_case_insensitively(project: Path):
    _write(project, "AGENTS.md", AGENTS.replace("## Release model", "## Rules"))
    assert "AGENTS.md: missing section `## Release model`" in _findings(project)


def test_claude_commands_section_is_required(project: Path):
    _write(project, "CLAUDE.md", MODELS.replace("## Commands", "## Setup"))
    assert "CLAUDE.md: missing section `## Commands`" in _findings(project)


# --- the models table ----------------------------------------------------------


def test_every_tier_row_is_required(project: Path):
    _write(
        project, "CLAUDE.md", MODELS.replace("| fix-review | sonnet | opus | — |\n", "")
    )
    assert "CLAUDE.md: `## Models` table has no `fix-review` row" in _findings(project)


def test_a_model_off_the_order_line_is_rejected(project: Path):
    _write(
        project, "CLAUDE.md", MODELS.replace("| coding | sonnet |", "| coding | gpt |")
    )
    assert "CLAUDE.md: `coding` floor `gpt` is not on the order line" in _findings(
        project
    )


def test_a_recommendation_below_its_floor_is_rejected(project: Path):
    broken = MODELS.replace(
        "| planning | opus | opus |", "| planning | opus | sonnet |"
    )
    _write(project, "CLAUDE.md", broken)
    assert "CLAUDE.md: `planning` recommends `sonnet` below its floor" in _findings(
        project
    )


# --- roadmap.md ----------------------------------------------------------------


def test_unknown_status_is_rejected(project: Path):
    _write(project, "roadmap.md", ROADMAP.replace("| outlined |", "| soon |"))
    assert "roadmap.md: `beta` has unknown status `soon`" in _findings(project)


def test_planned_row_must_link_an_existing_folder(project: Path):
    _write(
        project,
        "roadmap.md",
        ROADMAP.replace("| beta | outlined |", "| beta | planned |"),
    )
    assert "roadmap.md: `beta` is `planned` but links no folder" in _findings(project)
    linked = ROADMAP.replace(
        "| beta | outlined |", "| [beta](docs/features/beta/feature.md) | planned |"
    )
    _write(project, "roadmap.md", linked)
    assert (
        "roadmap.md: `beta` links `docs/features/beta/feature.md`, which is missing"
        in _findings(project)
    )


def test_outlined_row_must_not_link_a_folder(project: Path):
    linked = ROADMAP.replace(
        "| beta | outlined |", "| [beta](docs/features/beta/feature.md) | outlined |"
    )
    _write(project, "roadmap.md", linked)
    assert "roadmap.md: `beta` is `outlined` but links a folder" in _findings(project)


def test_folder_without_a_row_is_reported(project: Path):
    _write(project, "docs/features/gamma/feature.md", FEATURE)
    _write(project, "docs/features/gamma/manual_tests.md", "")
    assert (
        "roadmap.md: no row in `## Features` or `## Done` links "
        "`docs/features/gamma/feature.md`" in _findings(project)
    )


def test_status_must_agree_between_row_and_file(project: Path):
    _write(
        project, "docs/features/alpha/feature.md", FEATURE.replace("building", "built")
    )
    assert (
        "docs/features/alpha/feature.md: status `built` disagrees with roadmap.md "
        "`building`" in _findings(project)
    )


# --- feature.md ----------------------------------------------------------------


def test_missing_frontmatter_and_keys(project: Path):
    _write(project, "docs/features/alpha/feature.md", FEATURE.split("---\n", 2)[2])
    findings = _findings(project)
    assert "docs/features/alpha/feature.md: no frontmatter block" in findings
    for key in wc.FRONTMATTER_KEYS:
        assert f"docs/features/alpha/feature.md: frontmatter lacks `{key}`" in findings


def test_required_sections_and_chunk_headings(project: Path):
    no_checkpoint = FEATURE.replace("## Test checkpoint", "## Later")
    _write(project, "docs/features/alpha/feature.md", no_checkpoint)
    assert "docs/features/alpha/feature.md: missing section `## Test checkpoint`" in (
        _findings(project)
    )
    no_chunks = FEATURE.replace("### 1 — First chunk", "First chunk").replace(
        "### 2 — Second chunk", "Second chunk"
    )
    _write(project, "docs/features/alpha/feature.md", no_chunks)
    assert (
        "docs/features/alpha/feature.md: `## Chunks` has no `### <n> — <name>` heading"
        in _findings(project)
    )


def test_manual_tests_required_once_building(project: Path):
    (project / "docs/features/alpha/manual_tests.md").unlink()
    assert "docs/features/alpha/manual_tests.md: missing while `building`" in _findings(
        project
    )
    planned = FEATURE.replace("status: building", "status: planned")
    _write(project, "docs/features/alpha/feature.md", planned)
    _write(project, "roadmap.md", ROADMAP.replace("| building |", "| planned |"))
    assert _findings(project) == []


@pytest.mark.parametrize(
    "line",
    [
        'dark-ship: "the nav link is hidden"',
        'dark-ship: "`web/templates/base.html` hides the menu entry"',
        'dark-ship: "`_nav.html` and `_lineups.html` only"',
        "dark-ship: ",
        # Free prose is rejected however server-side it sounds: this one is
        # pure UI concealment, and no wording test separates it from a real
        # gate described in words.
        "dark-ship: the page is not linked anywhere in the interface",
        "dark-ship: a route guard in the fixtures router refuses opted-out callers",
        # Backticks around a prose word are not a reference: this is UI
        # concealment that would otherwise pass on the word `hidden` alone.
        "dark-ship: the page is `hidden` from the menu",
        'dark-ship: "the `nav entry` is not rendered"',
        'dark-ship: "`base.html hides the link`"',
    ],
)
def test_ui_only_dark_ship_is_rejected(project: Path, line: str):
    old = (
        'dark-ship: "`competitions.api_enabled`, checked in `shared/services/gate.py`"'
    )
    _write(project, "docs/features/alpha/feature.md", FEATURE.replace(old, line))
    assert (
        "docs/features/alpha/feature.md: `dark-ship` names no server-side "
        "enforcement point" in _findings(project)
    )


@pytest.mark.parametrize(
    "line",
    [
        'dark-ship: "`competitions.api_enabled`, checked in the service layer; '
        'the template `_nav.html` only mirrors it"',
        "dark-ship: feature branch",
        "dark-ship: `is_api_enabled` guards every read in the service layer",
        "dark-ship: checked in `shared/services/fixtures.py` before any write",
    ],
)
def test_server_side_dark_ship_is_accepted(project: Path, line: str):
    old = (
        'dark-ship: "`competitions.api_enabled`, checked in `shared/services/gate.py`"'
    )
    _write(project, "docs/features/alpha/feature.md", FEATURE.replace(old, line))
    assert _findings(project) == []


# --- depends-on ----------------------------------------------------------------


def _with_dependency(project: Path, entry: str) -> None:
    text = FEATURE.replace("depends-on: []", f"depends-on:\n  - {entry}")
    _write(project, "docs/features/alpha/feature.md", text)


def test_depends_on_must_name_feature_and_chunk(project: Path):
    _with_dependency(project, "alpha")
    assert (
        "docs/features/alpha/feature.md: depends-on `alpha` is not `<feature>/<chunk>`"
        in _findings(project)
    )


def test_depends_on_unknown_feature_or_chunk(project: Path):
    _with_dependency(project, "zeta/1 (on main)")
    assert (
        "docs/features/alpha/feature.md: depends-on `zeta/1 (on main)` names a "
        "feature with no folder" in _findings(project)
    )
    _with_dependency(project, "alpha/9")
    assert (
        "docs/features/alpha/feature.md: depends-on `alpha/9` names a chunk that "
        "does not exist" in _findings(project)
    )


def test_depends_on_existing_chunk_passes(project: Path):
    _with_dependency(project, "alpha/1 (on main)")
    assert _findings(project) == []


# --- weak spots ----------------------------------------------------------------


def test_weak_spot_cap(project: Path):
    rows = "".join(f"| C{i} | correctness | x | W1 | W1 |\n" for i in range(31))
    _write(project, "docs/weak-spots.md", WEAK_SPOTS + rows)
    assert "docs/weak-spots.md: 32 entries, cap is 30" in _findings(project)


def test_weak_spot_columns(project: Path):
    _write(project, "docs/weak-spots.md", WEAK_SPOTS.replace("Last fired", "Seen"))
    assert any(
        f.startswith("docs/weak-spots.md: table columns") for f in _findings(project)
    )


# --- regressions from the PR #133 review ---------------------------------------


def test_a_row_is_matched_to_its_folder_by_link_path_not_link_text(project: Path):
    """A row may name the feature anything; the link is what identifies it."""
    renamed = ROADMAP.replace(
        "| [alpha](docs/features/alpha/feature.md) |",
        "| [Alpha, the first feature](docs/features/alpha/feature.md) |",
    )
    _write(project, "roadmap.md", renamed)
    assert _findings(project) == []


def test_features_table_with_a_fourth_column_still_parses(project: Path):
    """Extra columns must not silently disable every folder-to-row check."""
    wide = ROADMAP.replace(
        "| Feature | Status | One line |\n|---------|--------|----------|",
        "| Feature | Status | One line | Owner |\n|---|---|---|---|",
    ).replace("| building | First |", "| building | First | me |")
    _write(
        project,
        "roadmap.md",
        wide.replace("| outlined | Second |", "| outlined | Second | me |"),
    )
    assert _findings(project) == []


def _with_after(alpha: str, beta: str) -> str:
    return (
        ROADMAP.replace(
            "| Feature | Status | One line |\n|---------|--------|----------|",
            "| Feature | Status | One line | After |\n|---|---|---|---|",
        )
        .replace("| building | First |", f"| building | First | {alpha} |")
        .replace("| outlined | Second |", f"| outlined | Second | {beta} |")
    )


def test_after_entries_naming_rows_pass(project: Path):
    _write(project, "roadmap.md", _with_after("—", "alpha"))
    assert _findings(project) == []


def test_an_after_entry_must_name_a_row(project: Path):
    _write(project, "roadmap.md", _with_after("", "alpha, gamma"))
    assert _findings(project) == [
        "roadmap.md: `beta` is after `gamma`, which has no row"
    ]


def test_after_entries_must_not_form_a_cycle(project: Path):
    _write(project, "roadmap.md", _with_after("beta", "`alpha`"))
    assert _findings(project) == [
        "roadmap.md: `After` entries form a cycle: `alpha` → `beta` → `alpha`"
    ]


def test_a_status_cell_carrying_more_than_one_word_is_read_whole(project: Path):
    """`building (paused)` is an unknown status, not an unparseable row."""
    _write(
        project, "roadmap.md", ROADMAP.replace("| outlined |", "| outlined (paused) |")
    )
    findings = _findings(project)
    assert "roadmap.md: `beta` has unknown status `outlined (paused)`" in findings
    # The other row still parsed, so alpha is not also reported as unlisted.
    assert not any("no `## Features` row links" in f for f in findings)


def test_models_order_line_without_a_parenthetical(project: Path):
    _write(project, "CLAUDE.md", MODELS.replace(" (extend when one ships)", ""))
    assert _findings(project) == []


def test_models_section_without_an_order_line(project: Path):
    without = MODELS.replace(
        "Order, weakest first: haiku < sonnet < opus < fable (extend when one ships).",
        "The tiers are below.",
    )
    _write(project, "CLAUDE.md", without)
    assert "CLAUDE.md: `## Models` has no `weakest first:` order line" in _findings(
        project
    )


def test_headings_inside_a_fenced_block_are_not_sections(project: Path):
    """A feature file quoting its own template must not gain phantom chunks."""
    fenced = FEATURE.replace(
        "## Test checkpoint",
        "## Notes\n\n```markdown\n## Chunks\n### 9 — not a real chunk\n```\n\n"
        "## Test checkpoint",
    )
    _write(project, "docs/features/alpha/feature.md", fenced)
    assert _findings(project) == []
    assert wc.chunk_numbers(fenced) == ["1", "2"]


def test_frontmatter_needs_a_closing_delimiter(project: Path):
    unterminated = FEATURE.replace(
        "checkpoint: It works\n---\n", "checkpoint: It works\n"
    )
    _write(project, "docs/features/alpha/feature.md", unterminated)
    assert "docs/features/alpha/feature.md: no frontmatter block" in _findings(project)


def test_frontmatter_reads_a_multi_line_list(project: Path):
    text = FEATURE.replace("depends-on: []", "depends-on:\n  - alpha/1\n  - alpha/2")
    meta = wc.frontmatter(text)
    assert meta is not None
    assert wc.list_items(meta["depends-on"]) == ["alpha/1", "alpha/2"]


def test_a_malformed_weak_spot_row_is_reported_not_counted(project: Path):
    _write(project, "docs/weak-spots.md", WEAK_SPOTS + "| Two | correctness |\n")
    assert "docs/weak-spots.md: row 2 has 2 cells, expected 5" in _findings(project)


# --- regressions from the PR #133 round-2 review --------------------------------


def test_a_signed_off_feature_lives_under_done(project: Path):
    """Sign-off moves the row to `## Done`; the folder stays and still counts."""
    moved = ROADMAP.replace(
        "| [alpha](docs/features/alpha/feature.md) | building | First |\n", ""
    ).replace(
        "| Feature | Shipped | One line |\n|---|---|---|",
        "| Feature | Shipped | One line |\n|---|---|---|\n"
        "| [alpha](docs/features/alpha/feature.md) | v1.0.0 | First |",
    )
    _write(project, "roadmap.md", moved)
    _write(
        project, "docs/features/alpha/feature.md", FEATURE.replace("building", "done")
    )
    assert _findings(project) == []


def test_two_rows_linking_one_folder_are_reported(project: Path):
    doubled = ROADMAP.replace(
        "| beta | outlined | Second |",
        "| [alpha again](docs/features/alpha/feature.md) | building | Dup |",
    )
    _write(project, "roadmap.md", doubled)
    assert "roadmap.md: two rows link `alpha`" in _findings(project)


def test_a_feature_folder_without_a_feature_file(project: Path):
    (project / "docs/features/gamma").mkdir(parents=True)
    assert "docs/features/gamma/feature.md: missing" in _findings(project)


def test_unterminated_frontmatter_does_not_swallow_a_body_rule(project: Path):
    """The body's horizontal rule must not be read as the block's close."""
    text = FEATURE.replace("checkpoint: It works\n---\n", "checkpoint: It works\n")
    text += "\nSome prose about the feature.\n\n---\n\nMore prose.\n"
    assert wc.frontmatter(text) is None
    _write(project, "docs/features/alpha/feature.md", text)
    assert "docs/features/alpha/feature.md: no frontmatter block" in _findings(project)


def test_headings_inside_a_tilde_fence_are_not_sections():
    text = "## One\n\n~~~markdown\n## Two\n~~~\n\nbody\n"
    assert list(wc.sections(text, 2)) == ["one"]


# --- regressions from the PR #133 round-3 review --------------------------------


def test_frontmatter_allows_blank_lines_and_comments(project: Path):
    """Cosmetic YAML must not read as "no frontmatter" plus four missing keys."""
    text = FEATURE.replace(
        "status: building\n",
        "# which stage this feature is at\nstatus: building\n\n",
    )
    meta = wc.frontmatter(text)
    assert meta is not None
    assert meta["status"] == "building"
    _write(project, "docs/features/alpha/feature.md", text)
    assert _findings(project) == []


def test_an_unclosed_fence_is_reported_not_silently_passed(project: Path):
    """Without this, every heading after the fence vanishes and the file passes."""
    _write(
        project, "docs/features/alpha/feature.md", FEATURE + "\n```markdown\nstray\n"
    )
    findings = _findings(project)
    assert (
        "docs/features/alpha/feature.md: a code fence is opened and never closed"
        in findings
    )
    assert not wc.fences_balanced("```\nopen\n")
    assert wc.fences_balanced("```\nclosed\n```\n")


def test_a_features_row_wins_over_a_done_row_for_the_same_folder(project: Path):
    """A feature listed in both is mid-reopen; the Features row is the live one."""
    both = ROADMAP.replace(
        "| Feature | Shipped | One line |\n|---|---|---|",
        "| Feature | Shipped | One line |\n|---|---|---|\n"
        "| [alpha](docs/features/alpha/feature.md) | v1.0.0 | First |",
    )
    _write(project, "roadmap.md", both)
    assert _findings(project) == []


def test_list_items_reads_the_inline_form():
    assert wc.list_items("[alpha/1, beta/2]") == ["alpha/1", "beta/2"]
    assert wc.list_items("['alpha/1']") == ["alpha/1"]
    assert wc.list_items("[]") == []


# --- regressions from the PR #133 round-4 review --------------------------------


def test_a_fence_closes_only_on_its_own_marker(project: Path):
    """A ~~~ block quoting a ``` example is balanced, not an imbalance.

    Counting fence lines by parity called those broken, and since the live
    repo is a fixture here that failed the suite on unrelated docs edits.
    """
    assert wc.fences_balanced("~~~markdown\n```bash\nx\n```\n~~~\n")
    assert wc.fences_balanced("```markdown\n~~~\n```\n")
    assert not wc.fences_balanced("~~~markdown\n```bash\nx\n```\n")
    nested = FEATURE.replace(
        "## Test checkpoint",
        "## Notes\n\n~~~markdown\n```bash\nrun it\n```\n~~~\n\n## Test checkpoint",
    )
    _write(project, "docs/features/alpha/feature.md", nested)
    assert _findings(project) == []


def test_a_status_a_folder_cannot_hold_is_reported(project: Path):
    _write(
        project,
        "docs/features/alpha/feature.md",
        FEATURE.replace("status: building", "status: outlined"),
    )
    assert (
        "docs/features/alpha/feature.md: status `outlined` is not one a feature "
        "folder can hold" in _findings(project)
    )


def test_missing_frontmatter_does_not_also_claim_a_status_disagreement(project: Path):
    """One cause, one finding set -- no phantom empty-status comparison."""
    _write(project, "docs/features/alpha/feature.md", FEATURE.split("---\n", 2)[2])
    findings = _findings(project)
    assert "docs/features/alpha/feature.md: no frontmatter block" in findings
    assert not any("disagrees with roadmap.md" in f for f in findings)


def test_an_indented_comment_is_not_read_as_a_list_item(project: Path):
    text = FEATURE.replace("depends-on: []", "depends-on:\n  # none yet\n  - alpha/1")
    meta = wc.frontmatter(text)
    assert meta is not None
    assert wc.list_items(meta["depends-on"]) == ["alpha/1"]
    _write(project, "docs/features/alpha/feature.md", text)
    assert _findings(project) == []


# --- regressions from the PR #133 round-5 review --------------------------------


def test_a_chunk_file_must_name_a_real_chunk(project: Path):
    _write(
        project, "docs/features/alpha/chunks/1-first.md", "Build model: sonnet — x\n"
    )
    assert _findings(project) == []
    _write(
        project, "docs/features/alpha/chunks/9-ghost.md", "Build model: sonnet — x\n"
    )
    assert (
        "docs/features/alpha/chunks/9-ghost.md: names chunk `9`, which feature.md "
        "has no heading for" in _findings(project)
    )


def test_a_chunk_file_must_carry_a_build_model_line(project: Path):
    """`/build` hard-gates on this line, so a file missing it stops the build."""
    _write(project, "docs/features/alpha/chunks/1-first.md", "# Chunk 1\n\nno model\n")
    assert (
        "docs/features/alpha/chunks/1-first.md: has no `Build model:` line"
        in _findings(project)
    )


def test_the_fixture_has_a_chunk_file_the_check_actually_reads():
    """Guards the check above against silently skipping the fixture tree.

    Globbed rather than pinned to one feature slug: the fixture is allowed to
    grow features, and this test should keep asserting the same property
    instead of breaking on a rename.
    """
    chunks = sorted((FIXTURE / "docs" / "features").glob("*/chunks/*.md"))
    assert chunks, (
        "no chunk file in fixture/ — test_the_bundled_fixture_passes "
        "would not exercise the Build model check"
    )
    assert all(wc.BUILD_MODEL.search(p.read_text(encoding="utf-8")) for p in chunks)


def test_a_done_row_without_a_link_is_named_as_such(project: Path):
    """The message must not claim `## Features` when `## Done` is the right home."""
    moved = ROADMAP.replace(
        "| [alpha](docs/features/alpha/feature.md) | building | First |\n", ""
    ).replace(
        "| Feature | Shipped | One line |\n|---|---|---|",
        "| Feature | Shipped | One line |\n|---|---|---|\n| alpha | v1.0.0 | First |",
    )
    _write(project, "roadmap.md", moved)
    _write(
        project, "docs/features/alpha/feature.md", FEATURE.replace("building", "done")
    )
    assert (
        "roadmap.md: no row in `## Features` or `## Done` links "
        "`docs/features/alpha/feature.md`" in _findings(project)
    )


def test_a_done_row_linking_a_missing_folder_is_ignored_not_crashing(project: Path):
    linked = ROADMAP.replace(
        "| Feature | Shipped | One line |\n|---|---|---|",
        "| Feature | Shipped | One line |\n|---|---|---|\n"
        "| [gone](docs/features/gone/feature.md) | v1.0.0 | Old |",
    )
    _write(project, "roadmap.md", linked)
    assert _findings(project) == []


@pytest.mark.parametrize(
    "rel", ["roadmap.md", "AGENTS.md", "CLAUDE.md", "docs/weak-spots.md"]
)
def test_check_fences_covers_every_parsed_file(project: Path, rel: str):
    path = project / rel
    path.write_text(
        path.read_text(encoding="utf-8") + "\n```markdown\nstray\n", encoding="utf-8"
    )
    assert f"{rel}: a code fence is opened and never closed" in _findings(project)


def test_slug_of_reads_a_row_linking_the_folder_itself():
    assert wc.slug_of("docs/features/alpha/feature.md") == "alpha"
    assert wc.slug_of("docs/features/alpha/") == "alpha"


# --- regressions from the PR #133 round-6 review --------------------------------


def test_a_malformed_frontmatter_line_names_itself(project: Path):
    """One bad line should not read as "no frontmatter" plus four missing keys."""
    _write(
        project,
        "docs/features/alpha/feature.md",
        FEATURE.replace("dark-ship:", "dark ship:"),
    )
    findings = _findings(project)
    assert (
        "docs/features/alpha/feature.md: frontmatter line is not `key: value`: "
        '`dark ship: "`competitions.api_enabled`, checked in '
        '`shared/services/gate.py`"`' in findings
    )
    assert not any("no frontmatter block" in f for f in findings)
    assert not any("frontmatter lacks" in f for f in findings)


@pytest.mark.parametrize(
    "ref,ok",
    [
        ("competitions.api_enabled", True),
        ("shared/services/gate.py", True),
        ("is_api_enabled", True),
        ("render_gate()", True),
        ("e.g.", False),
        ("hidden", False),
        (".", False),
        ("_", False),
    ],
)
def test_code_reference_needs_alphanumerics_around_its_separator(ref: str, ok: bool):
    assert bool(wc.CODE_REFERENCE.match(ref)) is ok


def test_a_done_only_row_still_checks_the_feature_status(project: Path):
    """A folder linked only from ## Done must actually say `done`."""
    moved = ROADMAP.replace(
        "| [alpha](docs/features/alpha/feature.md) | building | First |\n", ""
    ).replace(
        "| Feature | Shipped | One line |\n|---|---|---|",
        "| Feature | Shipped | One line |\n|---|---|---|\n"
        "| [alpha](docs/features/alpha/feature.md) | v1.0.0 | First |",
    )
    _write(project, "roadmap.md", moved)
    assert (
        "docs/features/alpha/feature.md: status `building` disagrees with "
        "roadmap.md `done`" in _findings(project)
    )


def test_a_malformed_frontmatter_line_does_not_hide_the_other_findings(project: Path):
    """One typo must not suppress the body and chunk-file checks for a feature.

    Bailing out on the frontmatter meant fixing the typo surfaced a second
    wave of findings on the next run, which is the silent skip the module
    docstring calls this script's worst failure mode.
    """
    broken = FEATURE.replace("dark-ship:", "dark ship:").replace(
        "## Test checkpoint", "## Later"
    )
    _write(project, "docs/features/alpha/feature.md", broken)
    _write(project, "docs/features/alpha/chunks/9-ghost.md", "no model line\n")
    findings = _findings(project)
    assert any("frontmatter line is not `key: value`" in f for f in findings)
    assert "docs/features/alpha/feature.md: missing section `## Test checkpoint`" in (
        findings
    )
    assert (
        "docs/features/alpha/chunks/9-ghost.md: names chunk `9`, which feature.md "
        "has no heading for" in findings
    )
    assert (
        "docs/features/alpha/chunks/9-ghost.md: has no `Build model:` line" in findings
    )
    # Still one cause, one finding: no phantom missing-key noise.
    assert not any("frontmatter lacks" in f for f in findings)
    assert not any("no frontmatter block" in f for f in findings)


# --- follow-up to PR #133: two bugs its final review found ----------------------


@pytest.mark.parametrize(
    "link,slug",
    [
        ("docs/features/alpha/feature.md", "alpha"),
        ("docs/features/alpha/", "alpha"),
        ("docs/features/alpha", "alpha"),
        # A dotted folder name looks suffixed (`.2-alpha`) and used to resolve
        # to its parent, leaving the real folder reported as unlisted.
        ("docs/features/v1.2-alpha/", "v1.2-alpha"),
        ("docs/features/v1.2-alpha/feature.md", "v1.2-alpha"),
    ],
)
def test_slug_of_resolves_a_dotted_folder_name(link: str, slug: str):
    assert wc.slug_of(link) == slug


def test_a_feature_folder_whose_name_contains_a_dot_is_matched(project: Path):
    """End to end: the dotted folder must not be reported as having no row."""
    _write(project, "docs/features/v1.2-alpha/feature.md", FEATURE)
    _write(project, "docs/features/v1.2-alpha/manual_tests.md", "")
    linked = ROADMAP.replace(
        "| beta | outlined | Second |",
        "| [v1.2-alpha](docs/features/v1.2-alpha/feature.md) | building | Dotted |",
    )
    _write(project, "roadmap.md", linked)
    assert _findings(project) == []


def test_an_unreadable_file_is_a_finding_not_a_traceback(project: Path):
    """The contract is a `<file>: <what>` line, including for bad bytes."""
    (project / "docs/features/alpha/feature.md").write_bytes(b"---\nstatus: \xff\xfe\n")
    findings = _findings(project)
    assert (
        "docs/features/alpha/feature.md: cannot be read (UnicodeDecodeError)"
        in findings
    )


@pytest.mark.parametrize(
    "rel",
    ["roadmap.md", "AGENTS.md", "CLAUDE.md", "docs/weak-spots.md"],
)
def test_every_fixed_path_reports_bad_bytes_rather_than_raising(
    project: Path, rel: str
):
    (project / rel).write_bytes(b"\xff\xfe not utf-8\n")
    findings = _findings(project)
    message = f"{rel}: cannot be read (UnicodeDecodeError)"
    assert message in findings
    # One cause, one finding: CLAUDE.md is read by the fence, section and
    # model checks, so without de-duplication this reported three times.
    assert findings.count(message) == 1


def test_an_unreadable_chunk_file_is_a_finding(project: Path):
    _write(
        project, "docs/features/alpha/chunks/1-first.md", "Build model: sonnet — x\n"
    )
    (project / "docs/features/alpha/chunks/1-first.md").write_bytes(b"\xff\xfe\n")
    assert (
        "docs/features/alpha/chunks/1-first.md: cannot be read (UnicodeDecodeError)"
        in _findings(project)
    )


def test_the_whole_run_survives_an_unreadable_file(project: Path):
    """One bad file must not stop the other checks from reporting."""
    (project / "AGENTS.md").write_bytes(b"\xff\xfe\n")
    _write(
        project,
        "docs/features/alpha/feature.md",
        FEATURE.replace("## Chunks", "## Bits"),
    )
    findings = _findings(project)
    assert "AGENTS.md: cannot be read (UnicodeDecodeError)" in findings
    assert "docs/features/alpha/feature.md: missing section `## Chunks`" in findings


def test_a_file_that_cannot_be_opened_is_reported_too(project: Path):
    """The OSError arm, not just the decode arm: a directory where a file goes."""
    path = project / "docs/features/alpha/feature.md"
    path.unlink()
    path.mkdir()
    assert any(
        f.startswith("docs/features/alpha/feature.md: cannot be read (")
        and "Error" in f
        for f in _findings(project)
    )


def test_an_unreadable_chunk_file_reports_only_that(project: Path):
    """No phantom `Build model:` finding on a file nobody could read."""
    _write(project, "docs/features/alpha/chunks/1-first.md", "placeholder\n")
    (project / "docs/features/alpha/chunks/1-first.md").write_bytes(b"\xff\xfe\n")
    findings = _findings(project)
    assert (
        "docs/features/alpha/chunks/1-first.md: cannot be read (UnicodeDecodeError)"
        in findings
    )
    assert not any("has no `Build model:` line" in f for f in findings)


def test_a_dependency_whose_feature_file_is_unreadable_is_named_accurately(
    project: Path,
):
    """Not "no folder" — the folder exists, and that finding points elsewhere."""
    _write(project, "docs/features/beta/feature.md", FEATURE)
    _write(project, "docs/features/beta/manual_tests.md", "")
    _write(
        project,
        "roadmap.md",
        ROADMAP.replace(
            "| beta | outlined | Second |",
            "| [beta](docs/features/beta/feature.md) | building | Second |",
        ),
    )
    _write(
        project,
        "docs/features/alpha/feature.md",
        FEATURE.replace("depends-on: []", "depends-on:\n  - beta/1"),
    )
    assert _findings(project) == []
    (project / "docs/features/beta/feature.md").write_bytes(b"\xff\xfe\n")
    findings = _findings(project)
    assert (
        "docs/features/alpha/feature.md: depends-on `beta/1` names a feature that "
        "could not be read" in findings
    )
    assert not any("names a feature with no folder" in f for f in findings)


def test_slug_of_ignores_extension_case():
    assert wc.slug_of("docs/features/alpha/feature.MD") == "alpha"
