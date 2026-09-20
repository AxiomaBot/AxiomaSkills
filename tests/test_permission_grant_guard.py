"""Tests for the committed-permission-grant guard.

The guard is the deterministic floor under a diff-only security review, and
`workflow init` ships a copy of it into every project this plugin scaffolds --
so a hole here is a hole in every consumer at once, and silently. Each test
builds a two-commit repository, puts exactly one thing in the head state, and
asserts the guard's verdict.

Only `permissions.allow` was ever checked. `defaultMode`,
`additionalDirectories` and the two MCP keys all grant strictly more and went
through untouched, which is the gap these tests pin shut.

The other gap was worse and is pinned here too: an earlier guard discarded the
parser's errors, so a settings file it could not read produced zero entries and
a confident "no new permission grants" on exit 0. A security control that
reports success when it could not read its input is worse than none, because the
green check gets believed.

These tests drove the port from shell to Python and validated it unchanged,
which is why they assert on behaviour and on messages rather than on how the
guard is implemented.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "check_committed_permission_grants.py"

pytestmark = pytest.mark.skipif(
    not shutil.which("git"),
    reason="the guard shells out to git",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def run_guard(
    tmp_path: Path,
    base: dict[str, dict],
    head: dict[str, dict | None],
) -> subprocess.CompletedProcess:
    """Commit ``base``, apply ``head`` (``None`` deletes), run the guard.

    Settings are given as ``{"relative/path.json": {...}}``. The head state is
    staged but not committed, which is what the guard sees on a PR: `git
    ls-files` for the tracked set, the worktree for the content.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")

    (repo / "README.md").write_text("base\n", encoding="utf-8")
    for rel, body in base.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    for rel, body in head.items():
        path = repo / rel
        if body is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    _git(repo, "add", "-A")

    return subprocess.run(
        [sys.executable, str(GUARD), base_sha],
        cwd=repo,
        capture_output=True,
        text=True,
    )


S = ".claude/settings.json"
LOCAL = ".claude/settings.local.json"


# --- the pre-existing behaviour, pinned so widening the guard did not break it


def test_a_repo_with_no_settings_at_all_passes(tmp_path: Path):
    assert run_guard(tmp_path, {}, {}).returncode == 0


def test_a_new_allow_entry_fails_and_is_named(tmp_path: Path):
    result = run_guard(tmp_path, {}, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    assert result.returncode == 1
    assert 'allow: "Bash(rm:*)"' in result.stderr
    assert S in result.stderr


def test_an_allow_entry_already_at_base_passes(tmp_path: Path):
    settings = {"permissions": {"allow": ["Bash(ls:*)"]}}
    assert run_guard(tmp_path, {S: settings}, {S: settings}).returncode == 0


def test_moving_a_grant_between_settings_files_is_not_a_new_grant(tmp_path: Path):
    """Keyed on the grant, not the path -- a split or rename is not an add."""
    result = run_guard(
        tmp_path,
        {S: {"permissions": {"allow": ["Bash(ls:*)"]}}},
        {S: None, LOCAL: {"permissions": {"allow": ["Bash(ls:*)"]}}},
    )
    assert result.returncode == 0


# --- defaultMode: the gap


@pytest.mark.parametrize("mode", ["bypassPermissions", "dontAsk", "acceptEdits"])
def test_a_granting_default_mode_fails(tmp_path: Path, mode: str):
    result = run_guard(tmp_path, {}, {S: {"permissions": {"defaultMode": mode}}})
    assert result.returncode == 1, f"{mode} was permitted"
    assert f'defaultMode: "{mode}"' in result.stderr


@pytest.mark.parametrize("mode", ["default", "plan"])
def test_a_non_granting_default_mode_passes(tmp_path: Path, mode: str):
    result = run_guard(tmp_path, {}, {S: {"permissions": {"defaultMode": mode}}})
    assert result.returncode == 0, result.stderr


def test_an_unknown_future_mode_fails_closed(tmp_path: Path):
    """An allowlist, not a blocklist: a mode invented later is reviewed."""
    result = run_guard(
        tmp_path, {}, {S: {"permissions": {"defaultMode": "yoloMode2030"}}}
    )
    assert result.returncode == 1
    assert 'defaultMode: "yoloMode2030"' in result.stderr


def test_a_granting_mode_already_at_base_is_not_newly_introduced(tmp_path: Path):
    settings = {"permissions": {"defaultMode": "bypassPermissions"}}
    assert run_guard(tmp_path, {S: settings}, {S: settings}).returncode == 0


# --- additionalDirectories: the other gap


def test_a_new_additional_directory_fails(tmp_path: Path):
    result = run_guard(
        tmp_path, {}, {S: {"permissions": {"additionalDirectories": ["/etc"]}}}
    )
    assert result.returncode == 1
    assert 'additionalDirectories: "/etc"' in result.stderr


def test_an_additional_directory_already_at_base_passes(tmp_path: Path):
    settings = {"permissions": {"additionalDirectories": ["../sibling"]}}
    assert run_guard(tmp_path, {S: settings}, {S: settings}).returncode == 0


# --- enableAllProjectMcpServers: a top-level key, not under `.permissions` ---


def test_enable_all_project_mcp_servers_true_fails(tmp_path: Path):
    result = run_guard(tmp_path, {}, {S: {"enableAllProjectMcpServers": True}})
    assert result.returncode == 1
    assert "enableAllProjectMcpServers: true" in result.stderr


def test_enable_all_project_mcp_servers_false_passes(tmp_path: Path):
    result = run_guard(tmp_path, {}, {S: {"enableAllProjectMcpServers": False}})
    assert result.returncode == 0, result.stderr


def test_enable_all_project_mcp_servers_absent_passes(tmp_path: Path):
    assert run_guard(tmp_path, {}, {S: {"model": "opus"}}).returncode == 0


def test_enable_all_project_mcp_servers_already_at_base_passes(tmp_path: Path):
    settings = {"enableAllProjectMcpServers": True}
    assert run_guard(tmp_path, {S: settings}, {S: settings}).returncode == 0


# --- shared behaviour


def test_all_five_kinds_are_reported_together(tmp_path: Path):
    result = run_guard(
        tmp_path,
        {},
        {
            S: {
                "permissions": {
                    "allow": ["Bash(curl:*)"],
                    "additionalDirectories": ["/srv"],
                    "defaultMode": "bypassPermissions",
                },
                "enableAllProjectMcpServers": True,
                "enabledMcpjsonServers": ["shady"],
            }
        },
    )
    assert result.returncode == 1
    for expected in (
        'allow: "Bash(curl:*)"',
        'additionalDirectories: "/srv"',
        'defaultMode: "bypassPermissions"',
        "enableAllProjectMcpServers: true",
        'enabledMcpjsonServers: "shady"',
    ):
        assert expected in result.stderr


def test_settings_without_a_permissions_block_pass(tmp_path: Path):
    assert run_guard(tmp_path, {}, {S: {"model": "opus"}}).returncode == 0


def test_a_settings_file_outside_dot_claude_is_not_scanned(tmp_path: Path):
    """The guard's scope is `.claude/settings*.json`, by name."""
    result = run_guard(
        tmp_path, {}, {"settings.json": {"permissions": {"allow": ["Bash(rm:*)"]}}}
    )
    assert result.returncode == 0


# --- enabledMcpjsonServers: the fifth grant kind


def test_a_named_mcp_server_is_a_grant(tmp_path: Path):
    result = run_guard(tmp_path, {}, {S: {"enabledMcpjsonServers": ["shady"]}})
    assert result.returncode == 1
    assert 'enabledMcpjsonServers: "shady"' in result.stderr


def test_a_named_mcp_server_already_at_base_passes(tmp_path: Path):
    settings = {"enabledMcpjsonServers": ["known"]}
    assert run_guard(tmp_path, {S: settings}, {S: settings}).returncode == 0


def test_an_empty_mcp_server_list_grants_nothing(tmp_path: Path):
    assert run_guard(tmp_path, {}, {S: {"enabledMcpjsonServers": []}}).returncode == 0


# --- failing closed: the guard must never pass on input it could not read


def _write_raw(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    """Commit a clean base, then stage a raw (possibly invalid) settings file."""
    result = run_guard(tmp_path, {}, {S: {"permissions": {"allow": []}}})
    assert result.returncode == 0, result.stderr
    repo = tmp_path / "repo"
    (repo / S).write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    return subprocess.run(
        [sys.executable, str(GUARD), "HEAD"], cwd=repo, capture_output=True, text=True
    )


@pytest.mark.parametrize(
    ("label", "body"),
    [
        ("truncated", "{ not json"),
        ("jsonc comment", '{\n // note\n "permissions": {"allow": ["Bash(rm:*)"]}\n}'),
    ],
)
def test_an_unreadable_settings_file_fails_closed(
    tmp_path: Path, label: str, body: str
):
    """It used to report such a file as carrying no grants, and exit 0."""
    result = _write_raw(tmp_path, body)
    assert result.returncode == 1, f"{label} was reported grant-free"
    assert "is not valid JSON" in result.stderr
    assert S in result.stderr


def test_the_guard_needs_no_external_json_tool(tmp_path: Path):
    """The predecessor shelled out to jq, and with jq off PATH it read nothing
    and passed every grant. Parsing is in-process now, so that whole class of
    fail-open is gone; this pins that the guard still works on a bare PATH."""
    repo = tmp_path / "repo"
    run_guard(tmp_path, {}, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    bin_dir = tmp_path / "emptybin"
    bin_dir.mkdir()
    for tool in ("git",):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PATH": str(bin_dir), "HOME": str(tmp_path)},
    )
    assert result.returncode == 1, "a real grant passed on a bare PATH"
    assert 'allow: "Bash(rm:*)"' in result.stderr


# --- the asymmetry: a broken file on the base branch must not deadlock the repo


BROKEN = '{\n // a comment makes this JSONC\n "permissions": {}\n}'


def _repo_with_broken_base(tmp_path: Path) -> tuple[Path, str]:
    """A repo whose base commit already carries an unparseable settings file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / ".claude").mkdir()
    (repo / S).write_text(BROKEN, encoding="utf-8")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, base_sha


def _run(repo: Path, base: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUARD), base], cwd=repo, capture_output=True, text=True
    )


def test_a_pr_repairing_a_broken_base_file_is_not_blocked(tmp_path: Path):
    """Failing on the base copy would fail every PR, including the fix.

    That deadlock is clearable only by pushing straight to the main branch,
    which is the thing this guard exists to make unnecessary.
    """
    repo, base = _repo_with_broken_base(tmp_path)
    (repo / S).write_text('{"permissions": {}}', encoding="utf-8")
    _git(repo, "add", "-A")
    result = _run(repo, base)
    assert result.returncode == 0, result.stderr
    assert "already unreadable at" in result.stderr, "the repair should still warn"


def test_a_broken_base_still_treats_every_head_grant_as_new(tmp_path: Path):
    """Not blocking is not the same as waving through."""
    repo, base = _repo_with_broken_base(tmp_path)
    (repo / S).write_text(
        '{"permissions": {"allow": ["Bash(rm:*)"]}}', encoding="utf-8"
    )
    _git(repo, "add", "-A")
    result = _run(repo, base)
    assert result.returncode == 1
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_base_side_enumeration_failure_fails_closed(tmp_path: Path):
    """Enumeration failing is not the same as finding nothing.

    Run outside a work tree the guard used to print OK and exit 0 with a real
    grant sitting in the tree. The base-side check is what fires here, which
    is why the assertion names it -- an earlier version of this test matched
    both messages and so proved nothing about either.
    """
    loose = tmp_path / "loose"
    (loose / ".claude").mkdir(parents=True)
    (loose / S).write_text(
        '{"permissions": {"allow": ["Bash(rm:*)"]}}', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"], cwd=loose, capture_output=True, text=True
    )
    assert result.returncode == 1
    # Outside a work tree the root check fires before enumeration does.
    assert "not inside a git work tree" in result.stderr


def test_head_side_enumeration_failure_fails_closed(tmp_path: Path):
    """The head-side check needs its own case: the base-side one fires first.

    A real work tree satisfies the base-side check, so the only way to reach
    this path is to make `git ls-files` specifically fail, which a shim does.
    """
    repo, base = _repo_with_broken_base(tmp_path)
    (repo / S).write_text(
        '{"permissions": {"allow": ["Bash(rm:*)"]}}', encoding="utf-8"
    )
    _git(repo, "add", "-A")

    real_git = shutil.which("git")
    assert real_git
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    (shim_dir / "git").write_text(
        # Match the subcommand wherever it falls: the guard now invokes
        # `git -c core.quotePath=false ls-files -z`, so `$1` is `-c`.
        f'#!/bin/sh\nfor a in "$@"; do\n'
        f'  [ "$a" = "ls-files" ] && exit 1\n'
        f'done\nexec {real_git} "$@"\n',
        encoding="utf-8",
    )
    (shim_dir / "git").chmod(0o755)

    env = dict(os.environ, PATH=f"{shim_dir}:{os.environ['PATH']}")
    result = subprocess.run(
        [sys.executable, str(GUARD), base],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1, "a failing git ls-files read as no settings files"
    assert "head-side enumeration" in result.stderr


@pytest.mark.parametrize(
    "body",
    [
        '{"enabledMcpjsonServers": "shady"}',  # an array field given a string
        '"just a string"',  # valid JSON, but not an object at all
    ],
)
def test_a_wrong_value_type_says_so_instead_of_blaming_the_syntax(
    tmp_path: Path, body: str
):
    """Valid JSON with a bad shape needs a different fix from a syntax error."""
    result = _write_raw(tmp_path, body)
    assert result.returncode == 1
    assert "valid JSON, but" in result.stderr
    assert "value types" in result.stderr


def test_an_empty_settings_file_is_not_read_as_grant_free(tmp_path: Path):
    """jq exits 0 on no input, so an empty file used to pass silently."""
    result = _write_raw(tmp_path, "")
    assert result.returncode == 1
    # Its own message: "no value at all" is a different fix from bad syntax.
    assert "holds no JSON value at all" in result.stderr


# --- round three: each of these was a separate silent hole in the read path


def test_a_tracked_settings_file_absent_from_disk_is_still_read(tmp_path: Path):
    """`[ -f ]` alone made the guard a permanent no-op under a sparse checkout.

    Base is read from git objects and head was read from the work tree, so a
    checkout excluding `.claude` left head finding nothing and every run green.
    """
    repo = tmp_path / "repo"
    run_guard(tmp_path, {}, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    (repo / S).unlink()
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 1, "a staged grant vanished with the work-tree copy"
    assert 'allow: "Bash(rm:*)"' in result.stderr


@pytest.mark.parametrize("value", ["true", 1, "yes"])
def test_a_non_boolean_mcp_flag_still_counts(tmp_path: Path, value):
    """`select(. == true)` ignored anything that was not a real boolean."""
    result = run_guard(tmp_path, {}, {S: {"enableAllProjectMcpServers": value}})
    assert result.returncode == 1, f"{value!r} was permitted"
    assert "enableAllProjectMcpServers:" in result.stderr


def test_a_valid_top_level_null_is_not_a_parse_error(tmp_path: Path):
    """`jq -e .` takes its status from the value, so `null` read as broken."""
    result = _write_raw(tmp_path, "null")
    assert result.returncode == 0, result.stderr


def test_a_passing_run_over_a_broken_base_emits_no_error_annotation(tmp_path: Path):
    """GitHub reads annotations off stderr, so a warning-only path must not
    use `::error::` — a green job was posting a red annotation anyway."""
    repo, base = _repo_with_broken_base(tmp_path)
    (repo / S).write_text('{"permissions": {}}', encoding="utf-8")
    _git(repo, "add", "-A")
    result = _run(repo, base)
    assert result.returncode == 0, result.stderr
    assert "::error::" not in result.stderr
    assert "::warning::" in result.stderr


def test_a_parse_failure_keeps_the_decoder_diagnostic(tmp_path: Path):
    """The predecessor swallowed it, leaving the fixer to guess which of
    several settings files was malformed and why."""
    result = _write_raw(tmp_path, "{ not json")
    assert result.returncode == 1
    assert "is not valid JSON" in result.stderr
    assert "line 1" in result.stderr, "the decoder's own detail was dropped"


def test_a_grant_containing_a_newline_cannot_hide_among_existing_lines(
    tmp_path: Path,
):
    """Grants are compared line by line, so a value holding a newline used to
    decompose into lines that each already existed at base -- and a string
    absent from base passed as "nothing new". `@json` keeps one grant on one
    line whatever it contains.
    """
    base = {"permissions": {"allow": ["Bash(ls:*)"]}}
    smuggled = "Bash(ls:*)\nallow: Bash(ls:*)"
    result = run_guard(tmp_path, {S: base}, {S: {"permissions": {"allow": [smuggled]}}})
    assert result.returncode == 1, "a grant absent from base was not reported"
    assert "allow:" in result.stderr


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root reads a 0o000 file regardless, so this would pass trivially",
)
def test_an_unreadable_work_tree_copy_falls_back_to_the_index(tmp_path: Path):
    """`cat` was assumed rather than tested, so a present-but-unreadable copy
    reported a successful read and the index fallback never ran.

    Skipped as root, where the permission bits do not bite. GitHub's runners
    are not root, so this does exercise the path in CI.
    """
    repo = tmp_path / "repo"
    run_guard(tmp_path, {}, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    (repo / S).chmod(0o000)
    try:
        result = subprocess.run(
            [sys.executable, str(GUARD), "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
    finally:
        (repo / S).chmod(0o644)
    assert result.returncode == 1, "the staged grant was lost with the work-tree read"
    assert 'allow: "Bash(rm:*)"' in result.stderr


# --- widening happens two ways: a grant added, or a restriction removed


NESTED = "packages/app/.claude/settings.json"


def test_a_nested_settings_file_is_not_invisible(tmp_path: Path):
    """Scoping to the repo root hid a live grant.

    `packages/app/.claude/settings.json` applies to anyone who opens Claude
    Code in `packages/app`, which in a monorepo is the normal way to work.
    """
    result = run_guard(
        tmp_path, {}, {NESTED: {"permissions": {"defaultMode": "bypassPermissions"}}}
    )
    assert result.returncode == 1, "a nested grant was invisible"
    assert 'defaultMode: "bypassPermissions"' in result.stderr
    assert NESTED in result.stderr


def test_a_nested_grant_already_at_base_passes(tmp_path: Path):
    settings = {"permissions": {"allow": ["Bash(ls:*)"]}}
    assert run_guard(tmp_path, {NESTED: settings}, {NESTED: settings}).returncode == 0


@pytest.mark.parametrize("kind", ["deny", "ask"])
def test_removing_a_restriction_is_reported(tmp_path: Path, kind: str):
    """Deleting a deny widens the surface exactly as adding an allow does."""
    result = run_guard(
        tmp_path,
        {S: {"permissions": {kind: ["Bash(curl:*)"]}}},
        {S: {"permissions": {}}},
    )
    assert result.returncode == 1, f"removing a {kind} entry was permitted"
    assert f'{kind}: "Bash(curl:*)"' in result.stderr
    assert "weakens a restriction" in result.stderr


def test_deleting_the_whole_settings_file_removes_its_restrictions(tmp_path: Path):
    result = run_guard(
        tmp_path, {S: {"permissions": {"deny": ["Bash(curl:*)"]}}}, {S: None}
    )
    assert result.returncode == 1
    assert 'deny: "Bash(curl:*)"' in result.stderr


def test_moving_a_restriction_within_one_scope_is_not_a_weakening(tmp_path: Path):
    """Splitting a scope's settings across two files changes nothing.

    `.claude/settings.json` and `.claude/settings.local.json` share a scope, so
    the union across them is what counts.
    """
    restriction = {"permissions": {"deny": ["Bash(curl:*)"]}}
    result = run_guard(tmp_path, {S: restriction}, {S: None, LOCAL: restriction})
    assert result.returncode == 0, result.stderr


def test_demoting_a_restriction_to_a_subdirectory_is_a_weakening(tmp_path: Path):
    """Any-depth discovery makes the path meaningful.

    A root `deny` covers the whole repo; the same entry in
    `packages/app/.claude/` covers only that subtree, so moving it down is a
    weakening even though the entry text is unchanged.
    """
    restriction = {"permissions": {"deny": ["Bash(curl:*)"]}}
    result = run_guard(tmp_path, {S: restriction}, {S: None, NESTED: restriction})
    assert result.returncode == 1, "a demoted restriction read as unchanged"
    assert 'deny: "Bash(curl:*)"' in result.stderr


def test_promoting_a_restriction_to_the_root_is_a_tightening(tmp_path: Path):
    """The other direction covers strictly more, so it must pass."""
    restriction = {"permissions": {"deny": ["Bash(curl:*)"]}}
    result = run_guard(tmp_path, {NESTED: restriction}, {NESTED: None, S: restriction})
    assert result.returncode == 0, result.stderr


def test_promoting_a_grant_to_the_root_is_a_new_grant(tmp_path: Path):
    """An allow scoped to one subtree is not the same as one repo-wide."""
    grant = {"permissions": {"allow": ["Bash(rm:*)"]}}
    result = run_guard(tmp_path, {NESTED: grant}, {NESTED: None, S: grant})
    assert result.returncode == 1, "a promoted grant read as unchanged"
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_keeping_every_restriction_passes(tmp_path: Path):
    settings = {"permissions": {"deny": ["Bash(curl:*)"], "ask": ["Bash(push:*)"]}}
    assert run_guard(tmp_path, {S: settings}, {S: settings}).returncode == 0


def test_adding_a_restriction_is_not_a_finding(tmp_path: Path):
    """Narrowing is always welcome; only widening is a finding."""
    result = run_guard(tmp_path, {}, {S: {"permissions": {"deny": ["Bash(curl:*)"]}}})
    assert result.returncode == 0, result.stderr


def test_an_unreadable_base_cannot_make_a_restriction_look_removed(tmp_path: Path):
    """The base-side warning must stay conservative in both directions."""
    repo, base = _repo_with_broken_base(tmp_path)
    (repo / S).write_text('{"permissions": {}}', encoding="utf-8")
    _git(repo, "add", "-A")
    result = _run(repo, base)
    assert result.returncode == 0, result.stderr
    assert "weakens a restriction" not in result.stderr


# --- round five: paths as bytes, and restrictions as an ordered pair


QUOTED = "pöckages/.claude/settings.json"


def test_a_non_ascii_path_is_not_c_quoted_into_invisibility(tmp_path: Path):
    """`git ls-files` C-quotes such a path, so it matched no pattern.

    A grant inside it passed clean: a fail-open in a script whose whole
    contract is the opposite.
    """
    result = run_guard(
        tmp_path, {}, {QUOTED: {"permissions": {"defaultMode": "bypassPermissions"}}}
    )
    assert result.returncode == 1, "a grant under a non-ASCII path was invisible"
    assert 'defaultMode: "bypassPermissions"' in result.stderr


def test_promoting_an_ask_to_a_deny_is_a_tightening(tmp_path: Path):
    """`deny` is stronger than `ask`, so this must not fail a security PR."""
    result = run_guard(
        tmp_path,
        {S: {"permissions": {"ask": ["Bash(curl:*)"]}}},
        {S: {"permissions": {"deny": ["Bash(curl:*)"]}}},
    )
    assert result.returncode == 0, result.stderr


def test_downgrading_a_deny_to_an_ask_is_a_weakening(tmp_path: Path):
    """The order only runs one way."""
    result = run_guard(
        tmp_path,
        {S: {"permissions": {"deny": ["Bash(curl:*)"]}}},
        {S: {"permissions": {"ask": ["Bash(curl:*)"]}}},
    )
    assert result.returncode == 1
    assert 'deny: "Bash(curl:*)"' in result.stderr


def test_dropping_plan_mode_is_a_weakening(tmp_path: Path):
    """`plan` is stricter than the default it falls back to."""
    result = run_guard(
        tmp_path,
        {S: {"permissions": {"defaultMode": "plan"}}},
        {S: {"permissions": {}}},
    )
    assert result.returncode == 1, "dropping plan mode went undetected"
    assert 'defaultMode: "plan"' in result.stderr


def test_dropping_the_default_mode_is_not_a_weakening(tmp_path: Path):
    """`default` is the baseline, so losing it changes nothing."""
    result = run_guard(
        tmp_path,
        {S: {"permissions": {"defaultMode": "default"}}},
        {S: {"permissions": {}}},
    )
    assert result.returncode == 0, result.stderr


def test_keeping_plan_mode_passes(tmp_path: Path):
    settings = {"permissions": {"defaultMode": "plan"}}
    assert run_guard(tmp_path, {S: settings}, {S: settings}).returncode == 0


def test_plan_to_bypass_is_both_a_new_grant_and_a_weakening(tmp_path: Path):
    result = run_guard(
        tmp_path,
        {S: {"permissions": {"defaultMode": "plan"}}},
        {S: {"permissions": {"defaultMode": "bypassPermissions"}}},
    )
    assert result.returncode == 1
    assert 'defaultMode: "bypassPermissions"' in result.stderr
    assert "weakens a restriction" in result.stderr


def test_the_guard_works_from_a_subdirectory(tmp_path: Path):
    """`git ls-tree -r` and `git ls-files` are both cwd-scoped.

    Run from a subdirectory, the guard reported a repo clean while a grant sat
    in the root settings file. It anchors itself to the repo root instead.
    """
    repo = tmp_path / "repo"
    run_guard(tmp_path, {S: {"permissions": {}}}, {})
    (repo / S).write_text(
        '{"permissions": {"allow": ["Bash(rm:*)"]}}', encoding="utf-8"
    )
    _git(repo, "add", "-A")
    sub = repo / "sub"
    sub.mkdir()
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"], cwd=sub, capture_output=True, text=True
    )
    assert result.returncode == 1, "a root grant was invisible from a subdirectory"
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_a_grant_is_found_when_the_base_had_none_at_all(tmp_path: Path):
    """An empty covering set is the awk `NR == FNR` trap.

    With no grants at base, every head entry read as already-seen and passed.
    """
    result = run_guard(
        tmp_path,
        {S: {"permissions": {}}},
        {S: {"permissions": {"allow": ["Bash(rm:*)"]}}},
    )
    assert result.returncode == 1, "a grant passed because base had none to compare"
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_a_deliberate_removal_can_be_overridden(tmp_path: Path):
    """A deny whose rule went obsolete has to be deletable."""
    repo = tmp_path / "repo"
    run_guard(
        tmp_path,
        {S: {"permissions": {"deny": ["Bash(curl:*)"]}}},
        {S: {"permissions": {}}},
    )
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD~0"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=dict(os.environ, ALLOW_PERMISSION_WEAKENING="1"),
    )
    assert result.returncode == 0, result.stderr


def test_the_override_does_not_excuse_an_added_grant(tmp_path: Path):
    """A committed allow has no legitimate in-repo form, so nothing waives it."""
    repo = tmp_path / "repo"
    run_guard(tmp_path, {}, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=dict(os.environ, ALLOW_PERMISSION_WEAKENING="1"),
    )
    assert result.returncode == 1, "the override waived an added grant"


# --- round six: two more restriction kinds, real ancestry, safe scope bytes


DEEP = "packages/app/.claude/settings.json"
MID = "packages/.claude/settings.json"


def test_removing_the_bypass_mode_lock_is_a_weakening(tmp_path: Path):
    """`disableBypassPermissionsMode` forbids the broadest mode outright."""
    result = run_guard(
        tmp_path,
        {S: {"permissions": {"disableBypassPermissionsMode": "disable"}}},
        {S: {"permissions": {}}},
    )
    assert result.returncode == 1
    assert "disableBypassPermissionsMode" in result.stderr


def test_re_permitting_a_disabled_mcp_server_is_a_weakening(tmp_path: Path):
    result = run_guard(tmp_path, {S: {"disabledMcpjsonServers": ["evil"]}}, {S: {}})
    assert result.returncode == 1
    assert 'disabledMcpjsonServers: "evil"' in result.stderr


def test_a_non_root_ancestor_covers_its_subtree(tmp_path: Path):
    """Moving a deny from `packages/app` to `packages` covers strictly more.

    A two-level model that only recognised the repo root reported this
    tightening as a weakening.
    """
    deny = {"permissions": {"deny": ["Bash(curl:*)"]}}
    result = run_guard(tmp_path, {DEEP: deny}, {DEEP: None, MID: deny})
    assert result.returncode == 0, result.stderr


def test_demoting_below_a_non_root_ancestor_is_a_weakening(tmp_path: Path):
    deny = {"permissions": {"deny": ["Bash(curl:*)"]}}
    result = run_guard(tmp_path, {MID: deny}, {MID: None, DEEP: deny})
    assert result.returncode == 1
    assert 'deny: "Bash(curl:*)"' in result.stderr


def test_narrowing_a_grant_to_a_subtree_is_not_a_new_grant(tmp_path: Path):
    """An allow at `packages` already covers `packages/app`."""
    grant = {"permissions": {"allow": ["Bash(rm:*)"]}}
    result = run_guard(tmp_path, {MID: grant}, {MID: None, DEEP: grant})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("dirname", ["a&b", "a|b", "a\\b"])
def test_a_tightening_under_an_awkward_scope_name_passes(tmp_path: Path, dirname: str):
    """The scope was spliced into a sed replacement, where `&` expands to the
    match and `|` ends the expression -- the one path-byte class the byte-safe
    enumeration work claimed to have closed.
    """
    path = f"{dirname}/.claude/settings.json"
    result = run_guard(
        tmp_path,
        {path: {"permissions": {"ask": ["Bash(curl:*)"]}}},
        {path: {"permissions": {"deny": ["Bash(curl:*)"]}}},
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("dirname", ["a&b", "a|b", "a\\b"])
def test_a_grant_under_an_awkward_scope_name_is_caught(tmp_path: Path, dirname: str):
    path = f"{dirname}/.claude/settings.json"
    result = run_guard(tmp_path, {}, {path: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    assert result.returncode == 1, "a grant under an awkward path name was missed"
    assert 'allow: "Bash(rm:*)"' in result.stderr


# --- the port's own regressions, found in review


BOM = b"\xef\xbb\xbf"
"""What an editor writes at the head of a UTF-8 file."""


def test_a_settings_file_with_a_byte_order_mark_is_read(tmp_path: Path):
    """jq accepted a leading BOM and strict UTF-8 does not.

    An editor-written settings file carrying one would have failed the guard on
    *every* PR in that repo, including ones that never touch the file.
    """
    repo = tmp_path / "repo"
    run_guard(tmp_path, {S: {"permissions": {}}}, {})
    (repo / S).write_bytes(BOM + b'{"permissions": {}}')
    _git(repo, "add", "-A")
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_a_grant_in_a_byte_order_marked_file_is_still_caught(tmp_path: Path):
    """Tolerating the BOM must not mean skipping the file."""
    repo = tmp_path / "repo"
    run_guard(tmp_path, {S: {"permissions": {}}}, {})
    (repo / S).write_bytes(BOM + b'{"permissions": {"allow": ["Bash(rm:*)"]}}')
    _git(repo, "add", "-A")
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_a_checkout_path_that_is_not_utf8_does_not_crash(tmp_path: Path):
    """The repo root was the one path decoded strictly.

    A checkout whose own directory name is not valid UTF-8 raised past the
    handler and died with a traceback instead of the annotation.
    """
    odd = tmp_path / os.fsdecode(b"repo_\xff")
    odd.mkdir()
    _git(odd, "init", "-q", ".")
    _git(odd, "config", "user.email", "t@example.com")
    _git(odd, "config", "user.name", "t")
    (odd / ".claude").mkdir()
    (odd / S).write_text('{"permissions": {}}', encoding="utf-8")
    (odd / "README.md").write_text("base\n", encoding="utf-8")
    _git(odd, "add", "-A")
    _git(odd, "commit", "-qm", "base")
    (odd / S).write_text('{"permissions": {"allow": ["Bash(rm:*)"]}}', encoding="utf-8")
    _git(odd, "add", "-A")
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"], cwd=odd, capture_output=True, text=True
    )
    assert "Traceback" not in result.stderr, result.stderr
    assert result.returncode == 1
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_undecodable_bytes_fail_closed_rather_than_collapsing(tmp_path: Path):
    """`errors="replace"` was a fail-open, not a convenience.

    Two different undecodable values both became U+FFFD, so a base grant and a
    different head grant collapsed onto one key and the change read as no
    change.
    """
    repo = tmp_path / "repo"
    run_guard(tmp_path, {S: {"permissions": {"allow": ["x"]}}}, {})
    (repo / S).write_bytes(b'{"permissions":{"allow":["Bash(a\xfeb)"]}}')
    _git(repo, "add", "-A")
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 1, "an undecodable settings file was waved through"
    assert "is not valid UTF-8" in result.stderr


def test_a_repo_directory_name_ending_in_a_space_still_works(tmp_path: Path):
    """`.strip()` trimmed part of the directory name, so `chdir` failed and the
    guard claimed it was not inside a work tree at all."""
    odd = tmp_path / "trailing space "
    odd.mkdir()
    _git(odd, "init", "-q", ".")
    _git(odd, "config", "user.email", "t@example.com")
    _git(odd, "config", "user.name", "t")
    (odd / ".claude").mkdir()
    (odd / S).write_text('{"permissions": {}}', encoding="utf-8")
    (odd / "README.md").write_text("base\n", encoding="utf-8")
    _git(odd, "add", "-A")
    _git(odd, "commit", "-qm", "base")
    (odd / S).write_text('{"permissions": {"allow": ["Bash(rm:*)"]}}', encoding="utf-8")
    _git(odd, "add", "-A")
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"], cwd=odd, capture_output=True, text=True
    )
    assert "not inside a git work tree" not in result.stderr
    assert result.returncode == 1
    assert 'allow: "Bash(rm:*)"' in result.stderr


def test_a_non_utf8_locale_still_emits_its_annotation(tmp_path: Path):
    """Encoding output with the filesystem encoding died on this script's own
    em dashes once the locale made that encoding ASCII."""
    repo = tmp_path / "repo"
    run_guard(tmp_path, {S: {"permissions": {}}}, {})
    (repo / S).write_text(
        '{"permissions": {"allow": ["Bash(rm:*)"]}}', encoding="utf-8"
    )
    _git(repo, "add", "-A")
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"],
        cwd=repo,
        capture_output=True,
        env=dict(os.environ, LC_ALL="C", PYTHONUTF8="0", PYTHONIOENCODING=""),
    )
    stderr = result.stderr.decode("utf-8", errors="replace")
    assert "Traceback" not in stderr, stderr
    assert result.returncode == 1
    assert "::error" in stderr


def test_a_lone_surrogate_in_a_value_does_not_kill_the_report(tmp_path: Path):
    """JSON can carry a lone surrogate through a `\\udXXX` escape, and no
    encoder can emit one. Printing it raw killed the run mid-report: with the
    override set it turned an exit 0 into an exit 1, and on the added-grant
    path it truncated the listing and skipped the weakened section entirely.
    """
    repo = tmp_path / "repo"
    run_guard(tmp_path, {S: {"permissions": {}}}, {})
    (repo / S).write_text(
        '{"permissions": {"allow": ["Bash(\\ud800)"]}}', encoding="utf-8"
    )
    _git(repo, "add", "-A")
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"], cwd=repo, capture_output=True, text=True
    )
    assert "Traceback" not in result.stderr, result.stderr
    assert result.returncode == 1
    assert "allow:" in result.stderr


def test_a_lone_surrogate_does_not_defeat_the_override(tmp_path: Path):
    """The same crash on the weakened-restriction path flipped a permitted run
    into a failure."""
    repo = tmp_path / "repo"
    run_guard(tmp_path, {S: {"permissions": {"deny": ["x"]}}}, {})
    (repo / S).write_text(
        '{"permissions": {"deny": ["Bash(\\ud800)"]}}', encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "surrogate deny")
    (repo / S).write_text('{"permissions": {}}', encoding="utf-8")
    _git(repo, "add", "-A")
    result = subprocess.run(
        [sys.executable, str(GUARD), "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=dict(os.environ, ALLOW_PERMISSION_WEAKENING="1"),
    )
    assert "Traceback" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stderr


def test_only_the_file_that_added_a_grant_is_blamed(tmp_path: Path):
    """The report dropped the scope, so it annotated every settings file
    holding the same value -- including one already on the base branch and
    outside the diff, told to remove a grant it had not added.
    """
    grant = {"permissions": {"allow": ["Bash(rm:*)"]}}
    result = run_guard(
        tmp_path,
        {NESTED: grant, S: {"permissions": {}}},
        {NESTED: grant, S: grant},
    )
    assert result.returncode == 1
    assert f"error file={S}" in result.stderr
    assert f"error file={NESTED}" not in result.stderr, (
        "a file that did not change was told to remove a grant"
    )
