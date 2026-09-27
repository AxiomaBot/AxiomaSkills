"""Tests for the renderer behind the `progress` skill.

The fixture is the passing case. The other tests each build the smallest
project that shows one reading rule, because the page's numbers are only as
good as the parsing under them: a checkbox miscounted, a dependency marked
met too early, or a feature put in the wrong wave is a wrong status report
that looks right.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO / "plugins" / "agentic-workflow" / "skills" / "progress" / "scripts"
) / "progress.py"
FIXTURE = REPO / "fixture"


def _load():
    """Import the script by path -- scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("progress", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pg = _load()

FEATURE = """\
---
status: {status}
depends-on: {depends}
dark-ship: `app.gate`
checkpoint: It works
---
# Feature: {slug}

## Chunks

### 1 — First

- [{tick}] a task
- [{tick}] another task

## Test checkpoint

Run `manual_tests.md` in this folder once every chunk is merged. Signed off
by: {signed}.
"""


def _project(tmp_path: Path, rows: str, done: str = "", after: bool = True) -> Path:
    header = (
        "| Feature | Status | One line | After |\n|---|---|---|---|\n"
        if after
        else "| Feature | Status | One line |\n|---|---|---|\n"
    )
    (tmp_path / "roadmap.md").write_text(
        f"# Roadmap — toy\n\n## Direction\nx\n\n## Features\n\n{header}{rows}\n"
        "## Done\n\n| Feature | Shipped | One line |\n|---|---|---|\n"
        f"{done}\n## Backlog\n- x\n",
        encoding="utf-8",
    )
    return tmp_path


def _feature(
    root: Path,
    slug: str,
    status: str,
    depends: str = "[]",
    tick: str = " ",
    signed: str = "<human, date>",
    manual: str | None = None,
) -> None:
    folder = root / "docs" / "features" / slug
    folder.mkdir(parents=True)
    (folder / "feature.md").write_text(
        FEATURE.format(
            status=status, depends=depends, slug=slug, tick=tick, signed=signed
        ),
        encoding="utf-8",
    )
    if manual is not None:
        (folder / "manual_tests.md").write_text(manual, encoding="utf-8")


def _row(slug: str, status: str, after: str | None = "", linked: bool = True) -> str:
    name = f"[{slug}](docs/features/{slug}/feature.md)" if linked else slug
    tail = "" if after is None else f" {after} |"
    return f"| {name} | {status} | {slug} |{tail}\n"


def _links(page_html: str) -> list[dict]:
    match = re.search(r'id="progress-links">(.*?)</script>', page_html)
    assert match
    return json.loads(match.group(1))


def _wave_slugs(page) -> list[list[str]]:
    return [[page.features[i].slug for i in wave] for wave in pg.waves(page)]


# --- the fixture ------------------------------------------------------------


def test_the_fixture_renders_shipped_then_waves(tmp_path: Path):
    out = tmp_path / "page.html"
    assert pg.main(["--root", str(FIXTURE), "--out", str(out)]) == 0
    page_html = out.read_text(encoding="utf-8")
    assert "<b>1</b> of 4 done" in page_html
    assert "demo-shop (fixture)" in page_html
    assert page_html.index("<h2>Shipped</h2>") < page_html.index("<h2>Ahead</h2>")
    assert "Can start now &middot; 2 in parallel" in page_html


def test_the_fixture_waves_follow_its_after_column():
    page = pg.build(FIXTURE)
    assert page.ordered
    assert _wave_slugs(page) == [["demo-widget", "demo-search"], ["demo-export"]]


def test_the_fixture_reads_checkpoints_and_sign_off():
    page = pg.build(FIXTURE)
    by_slug = {feature.slug: feature for feature in page.features}
    foundation, widget = by_slug["demo-foundation"], by_slug["demo-widget"]
    assert [(c.ticked, c.total) for c in foundation.checkpoints] == [(2, 2)]
    assert foundation.signed_off == "fixture author, 2026-09-18"
    assert [(c.ticked, c.total) for c in widget.checkpoints] == [(0, 2)]
    assert widget.signed_off is None


def test_the_fixture_links_only_features_that_are_ahead():
    page = pg.build(FIXTURE)
    widget = next(f for f in page.features if f.slug == "demo-widget")
    (dep,) = widget.depends
    assert (dep.slug, dep.chunk, dep.met) == ("demo-foundation", "1", True)
    # widget -> export is drawn; foundation -> widget is shipped, so a chip only.
    assert _links(pg.render(page)) == [{"from": 1, "to": 2, "met": False}]


# --- waves ------------------------------------------------------------------


def test_features_with_nothing_unmet_share_the_first_wave(tmp_path: Path):
    rows = (
        _row("a", "outlined", "base", linked=False)
        + _row("b", "outlined", "base", linked=False)
        + _row("c", "outlined", "a, b", linked=False)
        + _row("d", "outlined", "c", linked=False)
    )
    root = _project(tmp_path, rows, done="| base | v1 | x |\n")
    assert _wave_slugs(pg.build(root)) == [["a", "b"], ["c"], ["d"]]


def test_an_empty_after_cell_means_it_can_start_now(tmp_path: Path):
    rows = _row("a", "outlined", "—", linked=False) + _row(
        "b", "outlined", "", linked=False
    )
    assert _wave_slugs(pg.build(_project(tmp_path, rows))) == [["a", "b"]]


def test_a_met_chunk_dependency_does_not_hold_a_feature_back(tmp_path: Path):
    root = _project(tmp_path, _row("base", "building") + _row("top", "planned"))
    _feature(root, "base", "building", tick="x", manual="")
    _feature(root, "top", "planned", depends="\n  - base/1 (on main)")
    assert _wave_slugs(pg.build(root)) == [["base", "top"]]


def test_no_after_column_falls_back_to_table_order(tmp_path: Path):
    rows = _row("a", "outlined", None, False) + _row("b", "outlined", None, False)
    page = pg.build(_project(tmp_path, rows, after=False))
    assert not page.ordered
    assert _wave_slugs(page) == [["a"], ["b"]]
    page_html = pg.render(page)
    assert "has no <code>After</code> column" in page_html
    assert "Can start now" not in page_html


def test_a_cycle_does_not_hang_the_layout(tmp_path: Path):
    rows = _row("a", "outlined", "b", linked=False) + _row(
        "b", "outlined", "a", linked=False
    )
    waves = _wave_slugs(pg.build(_project(tmp_path, rows)))
    assert sorted(slug for wave in waves for slug in wave) == ["a", "b"]


# --- reading rules ----------------------------------------------------------


def test_a_chunk_dependency_waits_until_every_box_under_it_is_ticked(
    tmp_path: Path,
):
    root = _project(tmp_path, _row("base", "building") + _row("top", "planned"))
    _feature(root, "base", "building", manual="")
    _feature(root, "top", "planned", depends="\n  - base/1 (on main)")
    assert pg.build(root).features[1].depends[0].met is False

    feature_md = root / "docs" / "features" / "base" / "feature.md"
    feature_md.write_text(
        feature_md.read_text(encoding="utf-8").replace("- [ ]", "- [x]"),
        encoding="utf-8",
    )
    assert pg.build(root).features[1].depends[0].met is True


def test_after_and_depends_on_merge_without_repeating_a_feature(tmp_path: Path):
    rows = _row("base", "building") + _row("other", "outlined", linked=False)
    root = _project(tmp_path, rows + _row("top", "planned", "base, other"))
    _feature(root, "base", "building", manual="")
    _feature(root, "top", "planned", depends="\n  - base/1 (on main)")
    top = pg.build(root).features[2]
    assert [(d.entry, d.chunk) for d in top.depends] == [
        ("base/1", "1"),
        ("other", None),
    ]


def test_a_bare_dependency_waits_for_the_whole_feature(tmp_path: Path):
    root = _project(tmp_path, _row("base", "building") + _row("top", "planned"))
    _feature(root, "base", "building", tick="x", manual="")
    _feature(root, "top", "planned", depends="[base]")
    (dep,) = pg.build(root).features[1].depends
    assert (dep.slug, dep.chunk, dep.met) == ("base", None, False)


def test_a_dependency_on_a_built_feature_is_met(tmp_path: Path):
    root = _project(tmp_path, _row("base", "built") + _row("top", "planned"))
    _feature(root, "base", "built", manual="")
    _feature(root, "top", "planned", depends="[base]")
    assert pg.build(root).features[1].depends[0].met is True


def test_a_wrapped_sign_off_line_is_read_and_a_placeholder_is_not(tmp_path: Path):
    root = _project(tmp_path, _row("a", "built") + _row("b", "building"))
    _feature(root, "a", "built", signed="Ada B. Lovelace, 2026-09-27", manual="")
    _feature(root, "b", "building", manual="")
    a, b = pg.build(root).features
    assert a.signed_off == "Ada B. Lovelace, 2026-09-27"
    assert b.signed_off is None


def test_only_top_level_boxes_outside_fences_count_per_checkpoint(tmp_path: Path):
    manual = (
        "# Manual tests\n\n## First\n\n- [x] **one** (1)\n  - [ ] a nested step\n"
        "- [ ] **two** (1)\n\n```\n- [ ] an example in a fence\n```\n\n"
        "## Second\n\n- [x] **three** (2)\n\n## Notes\n\nNo boxes here.\n"
    )
    root = _project(tmp_path, _row("a", "building"))
    _feature(root, "a", "building", manual=manual)
    found = pg.build(root).features[0].checkpoints
    counts = [(c.name, c.ticked, c.total) for c in found]
    assert counts == [("First", 1, 2), ("Second", 1, 1)]


def test_a_status_disagreement_is_shown_not_resolved(tmp_path: Path):
    root = _project(tmp_path, _row("a", "building"))
    _feature(root, "a", "done", manual="")
    page_html = pg.render(pg.build(root))
    assert "feature.md says <code>done</code>" in page_html
    assert '<span class="pill flight">building</span>' in page_html


# --- options ----------------------------------------------------------------


def test_target_ends_the_page_and_hides_what_comes_after_it(tmp_path: Path):
    rows = _row("a", "outlined", "c", False) + _row("b", "outlined", "a", False)
    root = _project(tmp_path, rows + _row("c", "outlined", "", False))
    page = pg.build(root, target="b")
    assert [f.slug for f in page.features] == ["a", "b"]
    assert page.features[0].depends[0].upstream is None
    page_html = pg.render(page)
    assert _links(page_html) == [{"from": 0, "to": 1, "met": False}]
    assert "c &middot; not shown" in page_html
    assert '<span class="pill target">Target</span>' in page_html


@pytest.mark.parametrize(
    "args",
    [
        ["--target", "nope"],
        ["--target", "demo-foundation"],
        ["--note", "nope=text"],
        ["--note", "no-equals-sign"],
    ],
)
def test_a_bad_argument_is_exit_2_and_writes_nothing(tmp_path: Path, args):
    out = tmp_path / "page.html"
    assert pg.main(["--root", str(FIXTURE), "--out", str(out), *args]) == 2
    assert not out.exists()


def test_a_missing_roadmap_is_exit_2(tmp_path: Path):
    assert pg.main(["--root", str(tmp_path), "--out", str(tmp_path / "p.html")]) == 2


def test_fragment_leaves_the_document_skeleton_to_the_host():
    page = pg.build(FIXTURE)
    assert pg.render(page).startswith("<!doctype html>")
    fragment = pg.render(page, fragment=True)
    assert fragment.startswith("<title>")
    assert "<html" not in fragment and "<body" not in fragment


# --- escaping ---------------------------------------------------------------


def test_repository_text_and_arguments_are_escaped(tmp_path: Path):
    root = _project(tmp_path, "| x<script>alert(1)</script> | idea | a `<b>` | |\n")
    page = pg.build(root, notes={"x<script>alert(1)</script>": "<img src=x>"})
    page_html = pg.render(page, headline="<i>h</i>", summary="</script>")
    assert "<script>alert(1)" not in page_html
    assert "<img" not in page_html
    assert "<i>h</i>" not in page_html
    assert "<code>&lt;b&gt;</code>" in page_html
