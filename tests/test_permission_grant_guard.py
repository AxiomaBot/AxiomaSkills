"""Tests for the committed-permission-grant guard.

The guard is the deterministic floor under a diff-only security review, and
`workflow init` ships a copy of it into every project this plugin scaffolds --
so a hole here is a hole in every consumer at once, and silently.

It is an ABSOLUTE check: it reads the repository's own tree and fails if a
grant is present, with no reference to a base branch. These tests are written
to that contract. Each builds a one-commit repository holding exactly one
thing and asserts the verdict. There is nothing here about a grant being
added, moved, renamed or scoped, because the guard no longer has an opinion
about any of that -- only about whether a grant is there.

Two properties carry most of the weight, and each was once broken:

* every tracked `.claude/settings*.json` is read, at any depth, whatever its
  path bytes, from whatever directory the guard is invoked in, and from the
  index when the work tree cannot supply it;
* it FAILS CLOSED. A settings file it cannot read is an error, never a pass.
  A security control that reports success when it could not read its input is
  worse than none, because the green check gets believed.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "check_committed_permission_grants.py"

pytestmark = pytest.mark.skipif(
    not shutil.which("git"), reason="the guard shells out to git"
)

S = ".claude/settings.json"
NESTED = "packages/app/.claude/settings.json"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _invoke(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(GUARD)], cwd=cwd, capture_output=True, text=True
    )


def make_repo(tmp_path: Path, settings: dict[str, dict | str | bytes]) -> Path:
    """A committed repository holding ``settings``.

    Values are given as ``{"relative/path.json": {...}}``; a `str` or `bytes`
    value is written through verbatim, so a test can commit something that is
    not valid JSON at all.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")

    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    for rel, body in settings.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            path.write_bytes(body)
        elif isinstance(body, str):
            path.write_text(body, encoding="utf-8")
        else:
            path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "initial")
    return repo


def run_guard(
    tmp_path: Path, settings: dict[str, dict | str | bytes]
) -> subprocess.CompletedProcess:
    return _invoke(make_repo(tmp_path, settings))


# --- the five grant kinds ---------------------------------------------------


def test_a_repo_with_no_settings_at_all_passes(tmp_path: Path):
    result = run_guard(tmp_path, {})
    assert result.returncode == 0, result.stderr
    assert "0 tracked settings file(s)" in result.stdout


def test_an_allow_entry_fails_and_is_named(tmp_path: Path):
    result = run_guard(tmp_path, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    assert result.returncode == 1
    assert 'allow: "Bash(rm:*)"' in result.stderr
    assert S in result.stderr


def test_an_additional_directory_fails(tmp_path: Path):
    result = run_guard(
        tmp_path, {S: {"permissions": {"additionalDirectories": ["/etc"]}}}
    )
    assert result.returncode == 1
    assert 'additionalDirectories: "/etc"' in result.stderr


@pytest.mark.parametrize("mode", ["bypassPermissions", "dontAsk", "acceptEdits"])
def test_a_granting_default_mode_fails(tmp_path: Path, mode: str):
    """Each approves a whole class of action with no `allow` entry at all."""
    result = run_guard(tmp_path, {S: {"permissions": {"defaultMode": mode}}})
    assert result.returncode == 1, f"{mode} passed"
    assert f'defaultMode: "{mode}"' in result.stderr


@pytest.mark.parametrize("mode", ["default", "plan"])
def test_a_non_granting_default_mode_passes(tmp_path: Path, mode: str):
    result = run_guard(tmp_path, {S: {"permissions": {"defaultMode": mode}}})
    assert result.returncode == 0, result.stderr


def test_an_unknown_future_mode_fails_closed(tmp_path: Path):
    """The allowlist is the point: a mode shipped after this was written gets
    looked at rather than permitted by an enumeration nobody updated."""
    result = run_guard(tmp_path, {S: {"permissions": {"defaultMode": "yoloMode"}}})
    assert result.returncode == 1
    assert 'defaultMode: "yoloMode"' in result.stderr


def test_enable_all_project_mcp_servers_true_fails(tmp_path: Path):
    result = run_guard(tmp_path, {S: {"enableAllProjectMcpServers": True}})
    assert result.returncode == 1
    assert "enableAllProjectMcpServers: true" in result.stderr


@pytest.mark.parametrize("value", ["true", 1, "yes"])
def test_a_non_boolean_mcp_flag_still_counts(tmp_path: Path, value):
    """`"true"` and `1` are not booleans, but they are plainly not "off"."""
    result = run_guard(tmp_path, {S: {"enableAllProjectMcpServers": value}})
    assert result.returncode == 1, f"{value!r} passed"


def test_enable_all_project_mcp_servers_false_passes(tmp_path: Path):
    result = run_guard(tmp_path, {S: {"enableAllProjectMcpServers": False}})
    assert result.returncode == 0, result.stderr


def test_a_named_mcp_server_is_a_grant(tmp_path: Path):
    result = run_guard(tmp_path, {S: {"enabledMcpjsonServers": ["shady"]}})
    assert result.returncode == 1
    assert 'enabledMcpjsonServers: "shady"' in result.stderr


def test_an_empty_mcp_server_list_grants_nothing(tmp_path: Path):
    result = run_guard(tmp_path, {S: {"enabledMcpjsonServers": []}})
    assert result.returncode == 0, result.stderr


def test_all_five_kinds_are_reported_together(tmp_path: Path):
    """One run names every grant, so a fix is one pass rather than five."""
    result = run_guard(
        tmp_path,
        {
            S: {
                "permissions": {
                    "allow": ["Bash(rm:*)"],
                    "additionalDirectories": ["/etc"],
                    "defaultMode": "bypassPermissions",
                },
                "enableAllProjectMcpServers": True,
                "enabledMcpjsonServers": ["shady"],
            }
        },
    )
    assert result.returncode == 1
    for expected in (
        'allow: "Bash(rm:*)"',
        'additionalDirectories: "/etc"',
        'defaultMode: "bypassPermissions"',
        "enableAllProjectMcpServers: true",
        'enabledMcpjsonServers: "shady"',
    ):
        assert expected in result.stderr, f"{expected} was not reported"


def test_settings_without_a_permissions_block_pass(tmp_path: Path):
    result = run_guard(tmp_path, {S: {"model": "opus", "hooks": {}}})
    assert result.returncode == 0, result.stderr


def test_a_settings_file_outside_dot_claude_is_not_scanned(tmp_path: Path):
    """The name alone is not the signal; Claude Code reads `.claude/` only."""
    result = run_guard(
        tmp_path, {"settings.json": {"permissions": {"allow": ["Bash(rm:*)"]}}}
    )
    assert result.returncode == 0, result.stderr


# --- absolute, not differential --------------------------------------------


def test_a_grant_that_predates_this_guard_still_fails(tmp_path: Path):
    """The whole reason for the rewrite.

    The differential version compared head against a base that already held
    the grant, found no change, and passed -- forever. Nothing is
    grandfathered in now: the grant is in the tree, so the run is red.
    """
    repo = make_repo(tmp_path, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    _git(repo, "checkout", "-qb", "feature")
    (repo / "README.md").write_text("an unrelated change\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "touch something else")
    result = _invoke(repo)
    assert result.returncode == 1, "a pre-existing grant was grandfathered in"
    assert 'allow: "Bash(rm:*)"' in result.stderr


@pytest.mark.parametrize("kind", ["deny", "ask"])
def test_removing_a_restriction_is_deliberately_not_a_finding(
    tmp_path: Path, kind: str
):
    """Documenting a removal, not an oversight.

    Weakening detection needed the base tree plus rule ordering plus scope
    ancestry -- most of the old guard -- for the case a human reviewer reads
    most easily: a deleted `deny` line is right there in the diff. What a
    reviewer misses is a grant buried in a file they did not open, and that is
    what is kept.
    """
    repo = make_repo(tmp_path, {S: {"permissions": {kind: ["Bash(curl:*)"]}}})
    (repo / S).write_text('{"permissions": {}}', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"drop the {kind} rule")
    result = _invoke(repo)
    assert result.returncode == 0, result.stderr


def test_a_restriction_on_its_own_passes(tmp_path: Path):
    result = run_guard(
        tmp_path,
        {
            S: {
                "permissions": {"deny": ["Bash(curl:*)"], "ask": ["Bash(git push:*)"]},
                "disableBypassPermissionsMode": "disable",
                "disabledMcpjsonServers": ["shady"],
            }
        },
    )
    assert result.returncode == 0, result.stderr


# --- every tracked settings file, wherever it sits --------------------------


def test_a_nested_settings_file_is_not_invisible(tmp_path: Path):
    """`packages/app/.claude/settings.json` applies to anyone who opens Claude
    Code in `packages/app`, which in a monorepo is the normal way to work."""
    result = run_guard(
        tmp_path, {NESTED: {"permissions": {"defaultMode": "bypassPermissions"}}}
    )
    assert result.returncode == 1, "a nested grant was invisible"
    assert NESTED in result.stderr


@pytest.mark.parametrize("name", ["settings.local.json", "settings.dev.json"])
def test_every_settings_variant_is_read(tmp_path: Path, name: str):
    rel = f".claude/{name}"
    result = run_guard(tmp_path, {rel: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    assert result.returncode == 1, f"{rel} was not scanned"
    assert rel in result.stderr


@pytest.mark.parametrize("dirname", ["a&b", "a|b", "a\\b", "pakke-æøå"])
def test_a_grant_under_an_awkward_path_name_is_caught(tmp_path: Path, dirname: str):
    """git C-quotes a path holding a non-ASCII byte, a quote or a backslash,
    and a quoted path matches no pattern -- so a grant inside one would be
    invisible. `core.quotePath=false` with NUL delimiters is what keeps it
    visible."""
    path = f"{dirname}/.claude/settings.json"
    result = run_guard(tmp_path, {path: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    assert result.returncode == 1, "a grant under an awkward path name was missed"
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_a_directory_name_ending_in_a_space_is_still_read(tmp_path: Path):
    """The repo root is stripped with `rstrip("\\n")`, not `strip()`."""
    path = "trailing /.claude/settings.json"
    result = run_guard(tmp_path, {path: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    assert result.returncode == 1
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_the_guard_works_from_a_subdirectory(tmp_path: Path):
    """`git ls-files` is cwd-scoped, so the guard anchors itself to the root."""
    repo = make_repo(tmp_path, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    sub = repo / "sub"
    sub.mkdir()
    result = _invoke(sub)
    assert result.returncode == 1, "a root grant was invisible from a subdirectory"
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_a_tracked_settings_file_absent_from_disk_is_still_read(tmp_path: Path):
    """Reading only the work tree makes the guard a no-op under a sparse
    checkout, where `.claude` may not be materialised at all."""
    repo = make_repo(tmp_path, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    (repo / S).unlink()
    result = _invoke(repo)
    assert result.returncode == 1, "a tracked grant vanished with the work-tree copy"
    assert 'allow: "Bash(rm:*)"' in result.stderr


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root reads a 0o000 file regardless, so this would pass trivially",
)
def test_an_unreadable_work_tree_copy_falls_back_to_the_index(tmp_path: Path):
    """Skipped as root, where the permission bits do not bite. GitHub's
    runners are not root, so this does exercise the path in CI."""
    repo = make_repo(tmp_path, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    (repo / S).chmod(0o000)
    try:
        result = _invoke(repo)
    finally:
        (repo / S).chmod(0o644)
    assert result.returncode == 1, "the committed grant was lost with the work tree"
    assert 'allow: "Bash(rm:*)"' in result.stderr


# --- fail closed ------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "body"),
    [
        ("truncated", "{ not json"),
        ("jsonc comment", '{\n // note\n "permissions": {"allow": ["Bash(rm:*)"]}\n}'),
        ("trailing comma", '{"permissions": {"allow": ["Bash(rm:*)"],}}'),
    ],
)
def test_a_settings_file_it_cannot_parse_fails_closed(
    tmp_path: Path, label: str, body: str
):
    result = run_guard(tmp_path, {S: body})
    assert result.returncode == 1, f"{label} was reported grant-free"
    assert "is not valid JSON" in result.stderr
    assert S in result.stderr


def test_an_empty_settings_file_is_not_read_as_grant_free(tmp_path: Path):
    result = run_guard(tmp_path, {S: ""})
    assert result.returncode == 1
    # Its own message: "no value at all" is a different fix from bad syntax.
    assert "holds no JSON value at all" in result.stderr


@pytest.mark.parametrize(
    "body",
    [
        '{"enabledMcpjsonServers": "shady"}',  # an array field given a string
        '{"permissions": {"allow": "Bash(rm:*)"}}',  # ditto, nested
        '{"permissions": {"defaultMode": ["plan"]}}',  # a string field given an array
        '{"permissions": "wide open"}',  # permissions is not an object
        '"just a string"',  # valid JSON, but not an object at all
    ],
)
def test_a_wrong_value_type_says_so_instead_of_blaming_the_syntax(
    tmp_path: Path, body: str
):
    """Valid JSON with a bad shape needs a different fix from a syntax error."""
    result = run_guard(tmp_path, {S: body})
    assert result.returncode == 1
    assert "valid JSON, but" in result.stderr
    assert "value types" in result.stderr


def test_undecodable_bytes_fail_closed(tmp_path: Path):
    """Decoding with `errors="replace"` would silently repair these into
    U+FFFD and report whatever was left as the file's real contents."""
    result = run_guard(tmp_path, {S: b'{"permissions": {"allow": ["\xff\xfe"]}}'})
    assert result.returncode == 1
    assert "not valid UTF-8" in result.stderr


def test_a_byte_order_mark_is_not_a_parse_error(tmp_path: Path):
    """An editor may write one. Rejecting it would fail every PR in such a
    repo, which is a broken guard rather than a strict one."""
    result = run_guard(tmp_path, {S: "﻿" + '{"permissions": {}}'})
    assert result.returncode == 0, result.stderr


def test_a_valid_top_level_null_is_not_a_parse_error(tmp_path: Path):
    result = run_guard(tmp_path, {S: "null"})
    assert result.returncode == 0, result.stderr


def test_a_lone_surrogate_in_a_grant_does_not_kill_the_report(tmp_path: Path):
    """`\\ud800` parses into a lone surrogate no encoder can emit. Printing it
    raw aborted the run mid-report, which lost every finding after it."""
    result = run_guard(tmp_path, {S: '{"permissions": {"allow": ["\\ud800"]}}'})
    assert result.returncode == 1, result.stderr
    assert "allow:" in result.stderr
    assert "Traceback" not in result.stderr


def test_a_grant_containing_a_newline_is_still_one_reported_line(tmp_path: Path):
    """A value is JSON-encoded before it is printed, so an embedded newline
    cannot forge extra report lines."""
    result = run_guard(tmp_path, {S: {"permissions": {"allow": ["a\nb"]}}})
    assert result.returncode == 1
    assert 'allow: "a\\nb"' in result.stderr


def test_the_guard_refuses_to_pass_outside_a_repository(tmp_path: Path):
    """Not a git work tree means it enumerated nothing, which is not the same
    as finding nothing."""
    outside = tmp_path / "loose"
    outside.mkdir()
    result = subprocess.run(
        ["python3", str(GUARD)],
        cwd=outside,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path)},
    )
    assert result.returncode == 1
    assert "could not enumerate tracked files" in result.stderr


def test_one_unreadable_file_does_not_mask_a_grant_in_another(tmp_path: Path):
    """Every file is judged; the first failure does not end the run."""
    result = run_guard(
        tmp_path,
        {S: "{ not json", NESTED: {"permissions": {"allow": ["Bash(rm:*)"]}}},
    )
    assert result.returncode == 1
    assert "is not valid JSON" in result.stderr
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_a_clean_run_emits_no_error_annotation(tmp_path: Path):
    """GitHub turns any `::error` line red, so a passing run must emit none."""
    result = run_guard(tmp_path, {S: {"permissions": {"deny": ["Bash(curl:*)"]}}})
    assert result.returncode == 0, result.stderr
    assert "::error" not in result.stderr
    assert "1 tracked settings file(s)" in result.stdout
