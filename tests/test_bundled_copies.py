"""Pin the things this repo would otherwise keep in more than one place.

Two kinds of duplication are unavoidable here and one is not:

* `templates/` holds what the `workflow` skill's `init` mode copies into a
  consuming project, and this repo dogfoods the same guard from `scripts/`.
  Two copies, no check between them, and they drift the moment either is
  edited by hand -- a drifted guard being worse than none, since the version
  CI proves green is not the version consumers are handed.
* `fixture/` is a real consuming project, so it legitimately holds its own
  copy of what `init` wrote into it -- both the tier table (`CLAUDE.md`) and
  the two fixed sections of `templates/agents-sections.md` that never vary by
  project (`## Weak spots` in full; `## Release model`'s four floor bullets,
  everything but the project's own deploy-trigger line). Pinned, not
  eliminated. This is also where the fixture's own `## Release model` bullet
  drifted from the template by one clause before this file existed to catch
  it -- exactly the failure mode these tests are for.
* Prose *about* the tier table is not duplication anyone needs.
  `templates/models.md` is its single source; the skill and the README point
  at it. `test_the_tier_table_lives_in_exactly_one_place` is what keeps a
  fourth copy from growing back.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
MODELS_TEMPLATE = PLUGIN / "templates" / "models.md"

# The one row distinctive enough to find a stray copy of the table by.
TABLE_FINGERPRINT = "| security review | opus | opus |"

# Where the tier table may legitimately appear: its single source, and the
# fixture project, which holds it because `init` put it there.
TABLE_HOMES = {"templates/models.md", "fixture/CLAUDE.md"}

AGENTS_SECTIONS_TEMPLATE = PLUGIN / "templates" / "agents-sections.md"
FIXTURE_AGENTS = PLUGIN / "fixture" / "AGENTS.md"

# The one line in templates/agents-sections.md's `## Release model` that is
# meant to differ per project (how *this* project actually ships).
PLACEHOLDER_BULLET = re.compile(r"^-\s*<.*>\s*$")


def _fenced_markdown_body(text: str) -> str:
    """The content of the first ```markdown ... ``` fence in ``text``.

    ``templates/agents-sections.md`` is prose *about* the skeleton followed by
    one fence holding the skeleton itself -- the fence is what a project's
    ``AGENTS.md`` is built from, so it is the only part worth comparing
    against.
    """
    start = text.index("```markdown\n") + len("```markdown\n")
    end = text.index("\n```", start)
    return text[start:end]


def _load_workflow_check():
    script = PLUGIN / "skills" / "workflow" / "scripts" / "workflow_check.py"
    spec = importlib.util.spec_from_file_location("workflow_check_copies", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _table_tiers(text: str) -> tuple[str, ...]:
    """The first column of every data row of the `## Models` table."""
    tiers = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        first = line.strip("|").split("|")[0].strip()
        if first.lower() == "tier" or set(first) <= {"-", ":", " "}:
            continue
        tiers.append(first.lower())
    return tuple(tiers)


# --- files kept in two places on purpose ---


@pytest.mark.parametrize(
    ("ours", "shipped"),
    [
        (
            "scripts/check_committed_permission_grants.sh",
            "templates/check_committed_permission_grants.sh",
        ),
    ],
)
def test_the_guard_we_run_is_the_guard_we_ship(ours: str, shipped: str):
    run, ship = PLUGIN / ours, PLUGIN / shipped
    assert run.exists(), f"{ours} is missing"
    assert ship.exists(), f"{shipped} is missing"
    assert run.read_bytes() == ship.read_bytes(), (
        f"{ours} and {shipped} have drifted; apply the edit to both"
    )


# --- the tier table has exactly one source ---


def test_the_fixture_ships_the_models_template_untuned():
    """`fixture/` is what a project looks like straight after `init`.

    A real project may tune the Recommended column; the fixture deliberately
    does not, so equality is the assertion that keeps it honest as the thing
    every skill smoke-test reads against.
    """
    template = MODELS_TEMPLATE.read_text(encoding="utf-8").strip()
    claude_md = (PLUGIN / "fixture" / "CLAUDE.md").read_text(encoding="utf-8")
    start = claude_md.index("## Models")
    end = claude_md.index("## Layout")
    assert claude_md[start:end].strip() == template, (
        "fixture/CLAUDE.md's `## Models` section has drifted from "
        "templates/models.md; the fixture ships the template untuned"
    )


def test_the_layout_check_parses_the_tiers_the_template_defines():
    """Renaming a tier is one template edit plus `TIERS` -- this names it."""
    wc = _load_workflow_check()
    template_tiers = _table_tiers(MODELS_TEMPLATE.read_text(encoding="utf-8"))
    assert template_tiers, "no tier rows found in templates/models.md"
    assert tuple(t.lower() for t in wc.TIERS) == template_tiers, (
        "workflow_check.TIERS and templates/models.md disagree about the "
        "tiers; a tier renamed in one must be renamed in the other"
    )


def test_every_tier_recommendation_is_at_or_above_its_floor():
    """The floors are the method, so the single source must itself be sane."""
    wc = _load_workflow_check()
    text = MODELS_TEMPLATE.read_text(encoding="utf-8")
    order_match = re.search(r"weakest first:\s*([^(\n]+)", text)
    assert order_match, "templates/models.md has no `weakest first:` order line"
    order = [m.strip() for m in re.split(r"\s*<\s*", order_match.group(1)) if m.strip()]
    rows = 0
    for line in text.splitlines():
        cells = [c.strip().lower() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] not in [t.lower() for t in wc.TIERS]:
            continue
        rows += 1
        floor, recommended = cells[1], cells[2]
        assert floor in order, f"floor `{floor}` is not on the order line"
        assert recommended in order, f"`{recommended}` is not on the order line"
        assert order.index(recommended) >= order.index(floor), (
            f"{cells[0]} recommends `{recommended}` below its floor `{floor}`"
        )
    assert rows == len(wc.TIERS)


def test_the_tier_table_lives_in_exactly_one_place():
    """No fourth copy grows back into a skill, an agent, or the README."""
    strays = sorted(
        str(path.relative_to(PLUGIN))
        for path in PLUGIN.rglob("*.md")
        if ".git" not in path.parts
        and TABLE_FINGERPRINT in path.read_text(encoding="utf-8")
        and str(path.relative_to(PLUGIN)) not in TABLE_HOMES
    )
    assert not strays, (
        f"the tier table is reproduced in {strays}; templates/models.md is its "
        "single source — point at it instead of restating it"
    )


# --- fixture/AGENTS.md's fixed sections are pinned to their template ---


def test_the_weak_spots_section_is_pinned_to_its_template():
    """`## Weak spots` never varies by project -- it is entirely boilerplate."""
    wc = _load_workflow_check()
    template_body = _fenced_markdown_body(
        AGENTS_SECTIONS_TEMPLATE.read_text(encoding="utf-8")
    )
    template_text = wc.sections(template_body, 2)["weak spots"].strip()
    fixture_text = wc.sections(FIXTURE_AGENTS.read_text(encoding="utf-8"), 2)[
        "weak spots"
    ].strip()
    assert fixture_text == template_text, (
        "fixture/AGENTS.md's `## Weak spots` has drifted from "
        "templates/agents-sections.md; this section carries no project-specific "
        "content, so it should never differ"
    )


def test_the_release_model_floor_rules_are_pinned_to_their_template():
    """The four floor rules under `## Release model` never vary by project --
    only the closing "how this project actually ships" bullet does.
    """
    wc = _load_workflow_check()
    template_body = _fenced_markdown_body(
        AGENTS_SECTIONS_TEMPLATE.read_text(encoding="utf-8")
    )
    template_lines = wc.sections(template_body, 2)["release model"].splitlines()
    placeholder_idx = next(
        i
        for i, line in enumerate(template_lines)
        if PLACEHOLDER_BULLET.match(line.strip())
    )
    assert placeholder_idx > 0, (
        "templates/agents-sections.md's `## Release model` has no placeholder "
        "bullet to exclude -- this test's assumptions no longer hold"
    )
    fixed = "\n".join(template_lines[:placeholder_idx]).strip()

    fixture_text = wc.sections(FIXTURE_AGENTS.read_text(encoding="utf-8"), 2)[
        "release model"
    ].strip()
    assert fixture_text.startswith(fixed), (
        "fixture/AGENTS.md's `## Release model` floor rules (everything but "
        "the project's own deploy-trigger bullet) have drifted from "
        "templates/agents-sections.md"
    )
