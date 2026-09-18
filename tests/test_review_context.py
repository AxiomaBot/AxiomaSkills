"""Tests for the PR-review context builder the `pr-review` skill runs.

The allocation algorithm is the reason this is code and not prompt text: the
prose version it replaced once starved an entire directory's diff to zero
bytes and the reviewer still returned "no blocking issues". The four
properties asserted below are what make that unrepeatable.

These moved here from the first project to consume the plugin, so that the
copy under test is the copy the skill actually runs.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "pr-review"
    / "scripts"
    / "review_context.py"
)


def _load():
    """Import the script by path -- scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("review_context", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves annotations via sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rc = _load()


# --- allocate: the four guaranteed properties --------------------------------


def test_everything_fits_is_written_in_full():
    sizes = {"a": 10, "b": 20, "c": 30}
    assert rc.allocate(sizes, 1_000) == sizes


def test_total_never_exceeds_the_cap():
    sizes = {f"f{i}": 10_000 for i in range(20)}
    assert sum(rc.allocate(sizes, 50_000).values()) <= 50_000


def test_small_files_in_full_and_the_freed_budget_raises_the_rest():
    # 'small' fits the first equal share (33), so the 1000 budget minus its 3
    # bytes is split between the two oversized files -- 498 each, not 333.
    shares = rc.allocate({"small": 3, "big": 5_000, "huge": 9_000}, 1_000)
    assert shares["small"] == 3
    assert shares["big"] == shares["huge"] == (1_000 - 3) // 2
    assert sum(shares.values()) <= 1_000


def test_no_file_is_truncated_while_budget_goes_unspent():
    # The greedy predecessor cut files while leaving budget on the table; the
    # loop only stops raising shares once every survivor exceeds its share.
    sizes = {"a": 1, "b": 2, "c": 3, "d": 400, "e": 900}
    shares = rc.allocate(sizes, 1_000)
    unspent = 1_000 - sum(shares.values())
    cut = [p for p in sizes if shares[p] < sizes[p]]
    assert cut, "expected at least one truncated file in this scenario"
    assert unspent < min(sizes[p] - shares[p] for p in cut)


def test_no_file_is_ever_dropped():
    sizes = {f"f{i}": 1_000_000 for i in range(10)}
    shares = rc.allocate(sizes, 100_000)
    assert all(share == 10_000 for share in shares.values())


def test_allocation_is_order_independent():
    sizes = {"z": 5_000, "a": 3, "m": 700, "b": 40_000}
    forward = rc.allocate(sizes, 6_000)
    reversed_ = rc.allocate(dict(reversed(list(sizes.items()))), 6_000)
    assert forward == reversed_


# --- fit: truncation boundaries ---------------------------------------------


def test_content_that_fits_is_returned_untouched():
    body, boundary = rc.fit(b"line\n" * 3, 100, "a.py")
    assert boundary is None
    assert body == b"line\n" * 3


def _diff_shaped(lines: int) -> bytes:
    """A diff with the header git always emits, then `lines` hunk lines."""
    header = (
        b"diff --git a/a.py b/a.py\nindex 111..222 100644\n"
        b"--- a/a.py\n+++ b/a.py\n@@ -1,%d +1,%d @@\n" % (lines, lines)
    )
    return header + b"".join(f" line {i}\n".encode() for i in range(lines))


def test_truncation_cuts_at_a_line_boundary_and_marks_the_file():
    content = _diff_shaped(200)
    body, boundary = rc.fit(content, 400, "a.py")
    assert boundary == "line"
    assert len(body) <= 400
    assert b"[DIFF TRUNCATED for a.py at line boundary" in body
    # Every retained line is whole: the marker is the only trailing content.
    retained = body.split(b"[DIFF TRUNCATED")[0]
    assert retained.endswith(b"\n")
    assert content.startswith(retained)
    assert b" line 0\n" in retained, "a line cut must still carry the change"


def test_a_cut_that_would_retain_only_the_header_goes_to_a_byte_boundary():
    # The real app.css shape: a boundary exists (the header's own newlines) but
    # keeping only the preamble tells a reviewer nothing changed-files.txt
    # hasn't already said.
    content = _diff_shaped(1)[:-1] + b"+" + b"x" * 5_000 + b"\n"
    header_len = content.index(b"@@") + content[content.index(b"@@") :].index(b"\n")
    body, boundary = rc.fit(content, header_len + 120, "a.py")
    assert boundary == "byte"
    assert b"x" in body, "some of the change itself must be reviewable"


def test_a_single_oversized_line_falls_back_to_a_byte_boundary():
    # web/static/css/app.css (the committed Tailwind build) is the real case:
    # one enormous line, no boundary to cut at, and a line-only rule would
    # emit zero bytes -- which would break "no file is ever dropped".
    content = b"x" * 5_000
    body, boundary = rc.fit(content, 400, "web/static/css/app.css")
    assert boundary == "byte"
    assert len(body) <= 400
    assert body.startswith(b"x")
    assert b"at byte boundary" in body


def test_a_share_too_small_for_the_marker_still_names_the_file():
    # The one documented case where a file exceeds its share: naming it beats
    # silence, and the overshoot is one marker, not the file's content.
    body, boundary = rc.fit(b"Z" * 900, 10, "a.py")
    assert boundary == "byte"
    assert b"[DIFF TRUNCATED for a.py" in body
    assert b"Z" not in body
    assert len(body) == len(
        rc.TRUNCATION_MARKER.format(path="a.py", boundary="byte").encode()
    )


# --- process artifacts and prose context ------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "docs/features/w8-football-api/chunks/8-8-nav.md",
        "docs/audits/2026-09-15-workflow-redesign-pr1.md",
        "docs/audits/nested/deeper/report.md",
        "docs/plan.md",
    ],
)
def test_process_artifacts_are_recognised(path):
    assert rc.is_process_artifact(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/features/w8-football-api/feature.md",
        "docs/features/w8-football-api/manual_tests.md",
        "docs/deferred.md",
        "docs/weak-spots.md",
        "roadmap.md",
        # Scoped to markdown deliberately: a script under docs/audits/ is a
        # changed file like any other, not an auditor's prose report.
        "docs/audits/helper.py",
    ],
)
def test_everything_else_stays_in_the_diff(path):
    assert not rc.is_process_artifact(path)


def test_prose_gets_three_lines_of_context_and_code_gets_the_variant_value():
    quality, security = rc.VARIANTS
    assert rc.unified_for("AGENTS.md", quality) == 3
    assert rc.unified_for("web/routers/competitions.py", quality) == 80
    assert rc.unified_for("web/routers/competitions.py", security) == 120


def test_the_two_markers_share_no_token():
    omission = rc.OMISSION_MARKER.format(path="x.md")
    assert "TRUNCATED" not in omission
    assert "PROCESS ARTIFACT" not in rc.TRUNCATION_MARKER


# --- name-status parsing ----------------------------------------------------


def test_changed_paths_reports_a_rename_at_its_new_path():
    status = b"M\0AGENTS.md\0R100\0project_plan.md\0roadmap.md\0A\0docs/new.md\0"
    assert rc.changed_paths(status) == ["AGENTS.md", "docs/new.md", "roadmap.md"]


def test_changed_paths_keeps_a_path_git_would_have_c_quoted():
    # The whole reason the paths come from -z: in text output git renders this
    # as "\"odd\\tname.py\"", and a reconstructed quoted path diffs to nothing.
    assert rc.changed_paths(b"M\0odd\tname.py\0") == ["odd\tname.py"]


# --- end to end over a real repository --------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _rev(repo: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "keep.py").write_text("print('base')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def test_build_variant_omits_the_chunk_file_but_still_lists_it(
    repo: Path, tmp_path: Path
):
    chunk = repo / "docs" / "features" / "w8" / "chunks"
    chunk.mkdir(parents=True)
    (chunk / "1-thing.md").write_text("# Goal\nsecret rationale\n")
    (repo / "keep.py").write_text("print('changed')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")

    base = _rev(repo, "HEAD~1")
    out = tmp_path / "ctx"
    result = rc.build_variant(
        repo,
        base,
        rc.VARIANTS[0],
        out,
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )

    listed = (out / "quality" / "changed-files.txt").read_text()
    diff = (out / "quality" / "pr.diff").read_text()
    assert "docs/features/w8/chunks/1-thing.md" in listed, "scope must stay visible"
    assert "secret rationale" not in diff
    assert "PROCESS ARTIFACT" in diff
    assert "print('changed')" in diff
    assert result.omitted == ["docs/features/w8/chunks/1-thing.md"]
    assert result.truncated == []
    assert result.total <= rc.VARIANTS[0].total_cap


def test_build_variant_respects_the_cap_when_the_diff_is_oversized(
    repo: Path, tmp_path: Path
):
    for i in range(6):
        (repo / f"big{i}.py").write_text(f"# {i}\n" + "x = 1\n" * 4_000)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "big")
    base = _rev(repo, "HEAD~1")

    variant = rc.Variant("quality", code_unified=80, total_cap=20_000)
    out = tmp_path / "ctx"
    result = rc.build_variant(
        repo,
        base,
        variant,
        out,
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )

    assert result.total <= 20_000
    assert len(result.truncated) == 6
    diff = (out / "quality" / "pr.diff").read_bytes()
    # Every file reached the reviewer: no silent drops, each one marked.
    for i in range(6):
        assert f"big{i}.py".encode() in diff
    assert rc.report([result]).endswith("TRUNCATION: yes")


def test_build_artifacts_never_reach_a_reviewer(repo: Path, tmp_path: Path):
    # EXCLUDES is the only path filter in the builder; a regression here would
    # silently widen what both reviewers see.
    for rel in ("dist/bundle.js", "build/out.o", "coverage/index.html"):
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("generated\n")
    (repo / "notebook.ipynb").write_text('{"cells": []}\n')
    (repo / "keep.py").write_text("print('changed')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "artifacts")
    base = _rev(repo, "HEAD~1")

    result = rc.build_variant(
        repo,
        base,
        rc.VARIANTS[0],
        tmp_path / "ctx",
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )

    listed = (tmp_path / "ctx" / "quality" / "changed-files.txt").read_text()
    diff = (tmp_path / "ctx" / "quality" / "pr.diff").read_text()
    assert rc.changed_paths(rc.name_status_z(repo, base)) == ["keep.py"]
    assert result.file_count == 1
    for rel in ("dist/", "build/", "coverage/", "notebook.ipynb"):
        assert rel not in listed
        assert rel not in diff


def test_a_path_git_cannot_diff_is_marked_not_dropped(repo: Path, tmp_path: Path):
    # The failure mode is a path we reconstruct wrongly (a c-quoted or
    # non-UTF-8 filename): git returns nothing and a zero-byte entry would
    # break "no file is ever dropped" with no signal.
    (repo / "keep.py").write_text("print('changed')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")
    base = _rev(repo, "HEAD~1")

    status = b"M\0keep.py\0M\0ghost.py\0"
    out = tmp_path / "ctx"
    result = rc.build_variant(repo, base, rc.VARIANTS[0], out, status, status)

    diff = (out / "quality" / "pr.diff").read_text()
    assert "ghost.py" in result.truncated
    assert "[DIFF TRUNCATED for ghost.py" in diff
    assert rc.report([result]).endswith("TRUNCATION: yes")


def test_report_says_none_when_nothing_was_cut(repo: Path, tmp_path: Path):
    # `/pr-review` step 5 branches on this exact string.
    (repo / "keep.py").write_text("print('changed')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")
    base = _rev(repo, "HEAD~1")
    result = rc.build_variant(
        repo,
        base,
        rc.VARIANTS[0],
        tmp_path / "ctx",
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )
    assert rc.report([result]).endswith("TRUNCATION: none")


def test_main_writes_both_variants_and_summarises(repo: Path, tmp_path: Path, capsys):
    (repo / "keep.py").write_text("print('changed')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")
    out = tmp_path / "ctx"

    code = rc.main(
        [
            "--out-dir",
            str(out),
            "--repo",
            str(repo),
            "--merge-base",
            _rev(repo, "HEAD~1"),
        ]
    )

    assert code == 0
    printed = capsys.readouterr().out
    assert printed.startswith("merge base: ")
    assert printed.rstrip().endswith("TRUNCATION: none")
    for variant in rc.VARIANTS:
        assert (out / variant.name / "changed-files.txt").exists()
        assert (out / variant.name / "pr.diff").read_text().count("keep.py") >= 1


def test_main_fails_when_nothing_changed(repo: Path, tmp_path: Path):
    assert (
        rc.main(
            [
                "--out-dir",
                str(tmp_path / "ctx"),
                "--repo",
                str(repo),
                "--merge-base",
                _rev(repo, "HEAD"),
            ]
        )
        == 1
    )


def test_main_refuses_an_out_dir_inside_the_worktree(repo: Path):
    # A stray pr.diff in the worktree would ride the next diff it builds.
    with pytest.raises(SystemExit):
        rc.main(["--out-dir", str(repo / "ctx"), "--repo", str(repo)])


def test_prose_gets_narrow_context_in_the_written_diff(repo: Path, tmp_path: Path):
    # The byte saving the prose rule exists for, asserted where it lands:
    # 3 context lines for markdown, the variant's value for code.
    body = "".join(f"line {i}\n" for i in range(60))
    (repo / "doc.md").write_text(body)
    (repo / "code.py").write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    (repo / "doc.md").write_text(body.replace("line 30\n", "line thirty\n"))
    (repo / "code.py").write_text(body.replace("line 30\n", "line thirty\n"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "edit")
    base = _rev(repo, "HEAD~1")

    out = tmp_path / "ctx"
    rc.build_variant(
        repo,
        base,
        rc.VARIANTS[0],
        out,
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )
    diff = (out / "quality" / "pr.diff").read_text()
    code, prose = diff.split("diff --git a/code.py")[1].split("diff --git a/doc.md")
    # One changed line plus 3 lines of context either side, not 60.
    assert prose.count("\n line ") == 6
    assert code.count("\n line ") > 6


def test_a_deleted_file_reaches_the_reviewer_as_a_deletion(repo: Path, tmp_path: Path):
    (repo / "gone.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add")
    _git(repo, "rm", "-q", "gone.py")
    _git(repo, "commit", "-qm", "remove")
    base = _rev(repo, "HEAD~1")

    out = tmp_path / "ctx"
    result = rc.build_variant(
        repo,
        base,
        rc.VARIANTS[0],
        out,
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )
    diff = (out / "quality" / "pr.diff").read_text()
    assert result.truncated == []
    assert "deleted file mode" in diff
    assert "-x = 1" in diff


def test_merge_base_resolves_against_the_named_base_ref(repo: Path, tmp_path: Path):
    # The --base-ref path, for a PR that targets something other than main.
    _git(repo, "checkout", "-q", "-b", "other")
    (repo / "keep.py").write_text("print('other')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "other work")
    _git(repo, "checkout", "-q", "main")
    (repo / "main_only.py").write_text("print('main')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "main work")
    _git(repo, "checkout", "-q", "other")

    assert rc.merge_base(repo, "main") == _rev(repo, "main~1")
    code = rc.main(
        ["--out-dir", str(tmp_path / "ctx"), "--repo", str(repo), "--base-ref", "main"]
    )
    assert code == 0
    listed = (tmp_path / "ctx" / "quality" / "changed-files.txt").read_text()
    assert "keep.py" in listed
    assert "main_only.py" not in listed


def test_a_stale_variant_directory_is_never_handed_to_a_reviewer(
    repo: Path, tmp_path: Path
):
    out = tmp_path / "ctx"
    (out / "quality").mkdir(parents=True)
    (out / "quality" / "pr.diff").write_text("diff from an older head\n")
    (out / "quality" / "changed-files.txt").write_text("M\tolder.py\n")
    (repo / "keep.py").write_text("print('changed')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")
    base = _rev(repo, "HEAD~1")

    rc.build_variant(
        repo,
        base,
        rc.VARIANTS[0],
        out,
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )
    assert "older head" not in (out / "quality" / "pr.diff").read_text()
    assert "older.py" not in (out / "quality" / "changed-files.txt").read_text()


def test_a_directory_this_script_did_not_write_is_refused(tmp_path: Path):
    # A mistyped --out-dir must not delete someone's unrelated quality/.
    directory = tmp_path / "ctx" / "quality"
    directory.mkdir(parents=True)
    (directory / "someones_work.txt").write_text("keep me\n")
    with pytest.raises(RuntimeError, match="did not write"):
        rc.clear_variant_dir(directory)
    assert (directory / "someones_work.txt").exists()


def test_a_rename_is_written_at_its_new_path_only(repo: Path, tmp_path: Path):
    # What a rename actually looks like to a reviewer: the diff entry is keyed
    # to the destination, and changed-files.txt is where the old path survives.
    (repo / "old.py").write_text("x = 1\n" * 20)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add")
    _git(repo, "mv", "old.py", "new.py")
    (repo / "new.py").write_text("x = 1\n" * 20 + "y = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "rename and edit")
    base = _rev(repo, "HEAD~1")

    out = tmp_path / "ctx"
    result = rc.build_variant(
        repo,
        base,
        rc.VARIANTS[0],
        out,
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )
    listed = (out / "quality" / "changed-files.txt").read_text()
    diff = (out / "quality" / "pr.diff").read_text()
    assert result.file_count == 1
    assert "old.py" in listed and "new.py" in listed
    assert "b/new.py" in diff
    assert "+y = 2" in diff


def test_the_security_variant_gets_its_own_cap_and_context(repo: Path, tmp_path: Path):
    body = "".join(f"line {i}\n" for i in range(300))
    (repo / "code.py").write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    (repo / "code.py").write_text(body.replace("line 150\n", "line one-fifty\n"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "edit")
    base = _rev(repo, "HEAD~1")

    quality, security = rc.VARIANTS
    assert (security.code_unified, security.total_cap) == (120, 400_000)
    out = tmp_path / "ctx"
    for variant in (quality, security):
        rc.build_variant(
            repo,
            base,
            variant,
            out,
            rc.name_status(repo, base),
            rc.name_status_z(repo, base),
        )
    # 80 vs 120 lines of context either side of the one changed line.
    q = (out / "quality" / "pr.diff").read_text().count("\n line ")
    s = (out / "security" / "pr.diff").read_text().count("\n line ")
    assert q == 160
    assert s == 240


def test_a_single_huge_line_survives_the_whole_path(repo: Path, tmp_path: Path):
    # web/static/css/app.css's shape, end to end: allocation, the byte-boundary
    # cut, the marker, and the summary the skill branches on.
    (repo / "app.css").write_text("a{b:c}" * 5_000 + "\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "css")
    base = _rev(repo, "HEAD~1")

    variant = rc.Variant("quality", code_unified=80, total_cap=2_000)
    out = tmp_path / "ctx"
    result = rc.build_variant(
        repo,
        base,
        variant,
        out,
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )
    diff = (out / "quality" / "pr.diff").read_bytes()
    assert result.truncated == ["app.css"]
    assert b"at byte boundary" in diff
    assert b"a{b:c}" in diff, "the file must not reach the reviewer empty"
    assert len(diff) <= 2_000
    assert rc.report([result]).endswith("TRUNCATION: yes")


def test_every_truncation_marker_is_scannable_and_distinct():
    # A truncation scan must match all three truncation strings; an omission
    # scan must match none of them.
    truncation = [
        rc.TRUNCATION_MARKER.format(path="a.py", boundary="line"),
        rc.TRUNCATION_MARKER.format(path="a.py", boundary="byte"),
        rc.UNAVAILABLE_MARKER.format(path="a.py"),
    ]
    assert all(m.startswith("[DIFF TRUNCATED") for m in truncation)
    assert all("PROCESS ARTIFACT" not in m for m in truncation)
    assert "DIFF TRUNCATED" not in rc.OMISSION_MARKER.format(path="a.md")


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("docs/**", "docs/a/b/c.md", True),
        ("docs/**", "notdocs/a.md", False),
        ("docs/?.md", "docs/a.md", True),
        ("docs/?.md", "docs/ab.md", False),
    ],
)
def test_glob_translation_covers_its_wildcards(pattern, path, matches):
    # OMIT_PATTERNS only uses `*` and `**/` today; these pin the other two
    # branches so a future pattern cannot silently mis-compile.
    assert bool(rc._glob_to_regex(pattern).match(path)) is matches


def test_a_git_failure_reports_instead_of_raising(repo: Path, tmp_path, capsys):
    (repo / "keep.py").write_text("print('changed')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")

    code = rc.main(
        [
            "--out-dir",
            str(tmp_path / "ctx"),
            "--repo",
            str(repo),
            "--base-ref",
            "no-such-branch",
        ]
    )

    assert code == 1
    assert "Could not build the review context" in capsys.readouterr().err


def test_a_marker_only_entry_is_the_documented_cap_overshoot(
    repo: Path, tmp_path: Path
):
    # The integration pin for the docstring's "except for the markers noted":
    # a share below one marker, so each file is named rather than shown.
    for i in range(3):
        (repo / f"f{i}.py").write_text("x = 1\n" * 50)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "files")
    base = _rev(repo, "HEAD~1")

    variant = rc.Variant("quality", code_unified=80, total_cap=30)
    result = rc.build_variant(
        repo,
        base,
        variant,
        tmp_path / "ctx",
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )
    assert sorted(result.truncated) == ["f0.py", "f1.py", "f2.py"]
    # Over the cap, but bounded by one marker per file -- never by content.
    assert result.total > variant.total_cap
    diff = (tmp_path / "ctx" / "quality" / "pr.diff").read_text()
    assert "x = 1" not in diff
    assert diff.count("[DIFF TRUNCATED") == 3


def test_the_deliberate_inclusions_reach_the_reviewer(repo: Path, tmp_path: Path):
    # Both were decided deliberately and one -- the archive files -- regressed
    # once already: excluding them hid a /handoff reopen's section deletion.
    (repo / "poetry.lock").write_text('[[package]]\nname = "x"\n')
    archive = repo / "docs" / "archive"
    archive.mkdir(parents=True)
    (archive / "manual_tests_archive.md").write_text("# Archive\n\n## W7\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    (repo / "poetry.lock").write_text('[[package]]\nname = "y"\n')
    (archive / "manual_tests_archive.md").write_text("# Archive\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "edit both")
    base = _rev(repo, "HEAD~1")

    out = tmp_path / "ctx"
    rc.build_variant(
        repo,
        base,
        rc.VARIANTS[0],
        out,
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )
    diff = (out / "quality" / "pr.diff").read_text()
    assert 'name = "y"' in diff, "a dependency change is security-relevant"
    assert "-## W7" in diff, "an archive section deletion is worth reviewing"


def test_an_excluded_artifact_is_excluded_in_a_subdirectory_too(
    repo: Path, tmp_path: Path
):
    nested = repo / "notebooks"
    nested.mkdir()
    (nested / "x.ipynb").write_text('{"cells": []}\n')
    (repo / "keep.py").write_text("print('changed')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "nested artifact")
    base = _rev(repo, "HEAD~1")

    assert rc.changed_paths(rc.name_status_z(repo, base)) == ["keep.py"]


def test_changed_files_is_identical_for_both_variants(repo: Path, tmp_path: Path):
    # What makes "a reviewer is never misled about the PR's real scope" hold
    # for both of them.
    (repo / "keep.py").write_text("print('changed')\n")
    (repo / "doc.md").write_text("# doc\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")
    base = _rev(repo, "HEAD~1")

    out = tmp_path / "ctx"
    for variant in rc.VARIANTS:
        rc.build_variant(
            repo,
            base,
            variant,
            out,
            rc.name_status(repo, base),
            rc.name_status_z(repo, base),
        )
    listings = [
        (out / variant.name / "changed-files.txt").read_bytes()
        for variant in rc.VARIANTS
    ]
    assert listings[0] == listings[1]
    assert b"keep.py" in listings[0] and b"doc.md" in listings[0]


def test_a_diff_with_no_hunk_header_takes_the_byte_boundary():
    # A binary or mode-only diff has no @@ at all, so there is no body to
    # retain and the line boundary cannot be the right call.
    content = b"diff --git a/x.bin b/x.bin\nBinary files differ\n" + b"z" * 500
    body, boundary = rc.fit(content, 200, "x.bin")
    assert boundary == "byte"
    assert b"[DIFF TRUNCATED for x.bin at byte boundary" in body


@pytest.mark.parametrize("char", ["æ", "€", "𝄞"])
def test_a_byte_cut_never_splits_a_character(char):
    # A cut inside a multi-byte character would make pr.diff undecodable from
    # that point, costing the reviewer the rest of the file rather than the
    # few bytes saved.
    content = (char * 2_000).encode()
    marker_len = len(rc.TRUNCATION_MARKER.format(path="a.py", boundary="byte").encode())
    for share in range(marker_len + 1, marker_len + 20):
        body, boundary = rc.fit(content, share, "a.py")
        assert boundary == "byte"
        assert len(body) <= share
        body.decode()  # must not raise


def test_a_byte_cut_keeps_a_whole_character_when_it_fits():
    # The snap-back must not discard a character that is entirely inside the
    # share.
    marker = rc.TRUNCATION_MARKER.format(path="a.py", boundary="byte").encode()
    body, _ = rc.fit("æ".encode() * 100, len(marker) + 4, "a.py")
    assert body == "ææ".encode() + marker


def test_the_worktree_root_is_resolved_from_a_subdirectory(repo: Path, tmp_path: Path):
    # Root-relative changed paths paired with cwd-relative excludes would let
    # a generated artifact reach both reviewers; resolving the root once is
    # what keeps a subdirectory run identical to a root run.
    nested = repo / "web" / "routers"
    nested.mkdir(parents=True)
    (nested / "x.py").write_text("x = 1\n")
    dist = repo / "dist"
    dist.mkdir()
    (dist / "bundle.js").write_text("generated\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")

    assert rc.worktree_root(nested) == repo
    code = rc.main(
        [
            "--out-dir",
            str(tmp_path / "ctx"),
            "--repo",
            str(nested),
            "--merge-base",
            _rev(repo, "HEAD~1"),
        ]
    )
    assert code == 0
    listed = (tmp_path / "ctx" / "quality" / "changed-files.txt").read_text()
    diff = (tmp_path / "ctx" / "quality" / "pr.diff").read_text()
    assert "web/routers/x.py" in listed
    assert "x = 1" in diff, "a subdirectory run must still diff the real paths"
    assert "dist/" not in listed, "excludes must hold from a subdirectory too"


def test_main_aborts_on_an_out_dir_holding_foreign_files(repo: Path, tmp_path: Path):
    # What an operator actually hits on a mistyped --out-dir.
    (repo / "keep.py").write_text("print('changed')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")
    foreign = tmp_path / "ctx" / "quality"
    foreign.mkdir(parents=True)
    (foreign / "someones_work.txt").write_text("keep me\n")

    code = rc.main(
        [
            "--out-dir",
            str(tmp_path / "ctx"),
            "--repo",
            str(repo),
            "--merge-base",
            _rev(repo, "HEAD~1"),
        ]
    )
    assert code == 1
    assert (foreign / "someones_work.txt").exists()


def test_a_failure_on_the_second_variant_exits_non_zero(
    repo: Path, tmp_path: Path, monkeypatch
):
    # pr-review.md step 2 relies on this: a non-zero exit, and nothing on disk
    # from a previous head.
    (repo / "keep.py").write_text("print('changed')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")
    out = tmp_path / "ctx"
    (out / "security").mkdir(parents=True)
    (out / "security" / "pr.diff").write_text("diff from an older head\n")

    real = rc.build_variant
    calls = []

    def fail_on_second(*args, **kwargs):
        calls.append(args[2].name)
        if len(calls) > 1:
            raise RuntimeError("git exploded")
        return real(*args, **kwargs)

    monkeypatch.setattr(rc, "build_variant", fail_on_second)
    code = rc.main(
        [
            "--out-dir",
            str(out),
            "--repo",
            str(repo),
            "--merge-base",
            _rev(repo, "HEAD~1"),
        ]
    )
    assert code == 1
    assert not (out / "security" / "pr.diff").exists(), "no previous head's diff"


@pytest.mark.parametrize("variant_name", [v.name for v in rc.VARIANTS])
def test_a_chunk_file_is_omitted_for_every_variant(
    repo: Path, tmp_path: Path, variant_name
):
    chunk = repo / "docs" / "features" / "w8" / "chunks"
    chunk.mkdir(parents=True)
    (chunk / "1-thing.md").write_text("# Goal\nsecret rationale\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "chunk")
    base = _rev(repo, "HEAD~1")

    variant = next(v for v in rc.VARIANTS if v.name == variant_name)
    out = tmp_path / "ctx"
    rc.build_variant(
        repo,
        base,
        variant,
        out,
        rc.name_status(repo, base),
        rc.name_status_z(repo, base),
    )
    diff = (out / variant_name / "pr.diff").read_text()
    assert "secret rationale" not in diff
    assert "PROCESS ARTIFACT" in diff
