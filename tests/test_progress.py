"""Tests for the renderer behind the `progress` skill.

The fixture is the passing case. The other tests each build the smallest
project that shows one reading rule, because the page's numbers are only as
good as the parsing under them: a checkbox miscounted or a dependency marked
met too early is a wrong status report that looks right.
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


def _project(tmp_path: Path, rows: str, done: str = "") -> Path:
    (tmp_path / "roadmap.md").write_text(
        "# Roadmap — toy\n\n## Direction\nx\n\n"
        "## Features\n\n| Feature | Status | One line |\n|---|---|---|\n"
        f"{rows}\n## Done\n\n| Feature | Shipped | One line |\n|---|---|---|\n"
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


def _row(slug: str, status: str) -> str:
    return f"| [{slug}](docs/features/{slug}/feature.md) | {status} | {slug} |\n"


def _edges(page_html: str) -> list[dict]:
    match = re.search(r'id="progress-edges">(.*?)</script>', page_html)
    assert match
    return json.loads(match.group(1))


# --- the fixture ------------------------------------------------------------


def test_the_fixture_renders_in_roadmap_order(tmp_path: Path):
    out = tmp_path / "page.html"
    assert pg.main(["--root", str(FIXTURE), "--out", str(out)]) == 0
    page_html = out.read_text(encoding="utf-8")
    names = ["demo-foundation", "demo-widget", "demo-export", "demo-search"]
    positions = [page_html.index(f'class="name">{name}<') for name in names]
    assert positions == sorted(positions)
    assert "<b>1</b> of 4 done" in page_html
    assert "demo-shop (fixture)" in page_html


def test_the_fixture_reads_checkpoints_and_sign_off():
    page = pg.build(FIXTURE)
    by_slug = {feature.slug: feature for feature in page.features}
    foundation, widget = by_slug["demo-foundation"], by_slug["demo-widget"]
    assert [(c.ticked, c.total) for c in foundation.checkpoints] == [(2, 2)]
    assert foundation.signed_off == "fixture author, 2026-09-18"
    assert [(c.ticked, c.total) for c in widget.checkpoints] == [(0, 2)]
    assert widget.signed_off is None


def test_the_fixture_dependency_is_met_and_drawn():
    page = pg.build(FIXTURE)
    widget = next(f for f in page.features if f.slug == "demo-widget")
    (dep,) = widget.depends
    assert (dep.slug, dep.chunk, dep.met, dep.upstream) == (
        "demo-foundation",
        "1",
        True,
        0,
    )
    assert _edges(pg.render(page)) == [{"from": 0, "to": 1, "met": True}]


# --- reading rules ----------------------------------------------------------


def test_a_chunk_dependency_waits_until_every_box_under_it_is_ticked(
    tmp_path: Path,
):
    root = _project(tmp_path, _row("base", "building") + _row("top", "planned"))
    _feature(root, "base", "building", manual="")
    _feature(root, "top", "planned", depends="\n  - base/1 (on main)")
    top = pg.build(root).features[1]
    assert top.depends[0].met is False

    feature_md = root / "docs" / "features" / "base" / "feature.md"
    feature_md.write_text(
        feature_md.read_text(encoding="utf-8").replace("- [ ]", "- [x]"),
        encoding="utf-8",
    )
    assert pg.build(root).features[1].depends[0].met is True


def test_a_bare_feature_dependency_waits_for_the_whole_feature(tmp_path: Path):
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


def test_an_annotated_status_styles_by_its_first_word(tmp_path: Path):
    root = _project(tmp_path, "| thing | outlined (paused) | x |\n")
    assert pg.build(root).features[0].kind == "outlined"


# --- options ----------------------------------------------------------------


def test_target_ends_the_page_and_hides_edges_past_it(tmp_path: Path):
    rows = _row("a", "building") + "| b | outlined | x |\n" + _row("c", "planned")
    root = _project(tmp_path, rows)
    _feature(root, "a", "building", depends="[c]", manual="")
    _feature(root, "c", "planned")
    page = pg.build(root, target="b")
    assert [f.slug for f in page.features] == ["a", "b"]
    assert page.features[0].depends[0].upstream is None
    page_html = pg.render(page)
    assert _edges(page_html) == []
    assert "c &middot; not shown" in page_html
    assert '<span class="pill target">Target</span>' in page_html


@pytest.mark.parametrize(
    "args",
    [
        ["--target", "nope"],
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
    root = _project(tmp_path, "| x<script>alert(1)</script> | idea | a `<b>` |\n")
    page = pg.build(root, notes={"x<script>alert(1)</script>": "<img src=x>"})
    page_html = pg.render(page, headline="<i>h</i>", summary="</script>")
    assert "<script>alert(1)" not in page_html
    assert "<img" not in page_html
    assert "<i>h</i>" not in page_html
    assert "<code>&lt;b&gt;</code>" in page_html
