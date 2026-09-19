"""Tests for the committed-permission-grant guard.

The guard is the deterministic floor under a diff-only security review, and
`workflow init` ships a copy of it into every project this plugin scaffolds --
so a hole here is a hole in every consumer at once, and silently. Each test
builds a two-commit repository, puts exactly one thing in the head state, and
asserts the guard's verdict.

Only `permissions.allow` was ever checked. `defaultMode`,
`additionalDirectories` and the two MCP keys all grant strictly more and went
through untouched, which is the gap these tests pin shut.

The other gap was worse and is pinned here too: the guard used to discard jq's
stderr and exit status, so a settings file it could not parse -- or jq missing
from the runner -- produced zero grant lines and a confident "no new permission
grants" on exit 0. A security control that reports success when it could not
read its input is worse than none, because the green check gets believed.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "check_committed_permission_grants.sh"

pytestmark = pytest.mark.skipif(
    not (shutil.which("jq") and shutil.which("git")),
    reason="the guard shells out to git and jq",
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
        ["bash", str(GUARD), base_sha],
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
        ["bash", str(GUARD), "HEAD"], cwd=repo, capture_output=True, text=True
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


def test_a_missing_jq_fails_closed_rather_than_passing_everything(tmp_path: Path):
    """With jq off PATH the guard could read nothing, so it passed everything."""
    repo = tmp_path / "repo"
    run_guard(tmp_path, {}, {S: {"permissions": {"allow": ["Bash(rm:*)"]}}})
    bin_dir = tmp_path / "emptybin"
    bin_dir.mkdir()
    for tool in ("git", "grep", "sort", "comm", "sed", "mktemp", "rm", "cat", "bash"):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    result = subprocess.run(
        ["bash", str(GUARD), "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PATH": str(bin_dir), "HOME": str(tmp_path)},
    )
    assert result.returncode == 1, "a repo with a real grant passed with no jq"
    assert "jq is not installed" in result.stderr


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
        ["bash", str(GUARD), base], cwd=repo, capture_output=True, text=True
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
        ["bash", str(GUARD), "HEAD"], cwd=loose, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "base-side enumeration" in result.stderr


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
        f'#!/bin/sh\nif [ "$1" = "ls-files" ]; then exit 1; fi\nexec {real_git} "$@"\n',
        encoding="utf-8",
    )
    (shim_dir / "git").chmod(0o755)

    env = dict(os.environ, PATH=f"{shim_dir}:{os.environ['PATH']}")
    result = subprocess.run(
        ["bash", str(GUARD), base],
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
        ["bash", str(GUARD), "HEAD"], cwd=repo, capture_output=True, text=True
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


def test_a_parse_failure_keeps_jq_own_diagnostic(tmp_path: Path):
    """The message used to be swallowed by `2>/dev/null`."""
    result = _write_raw(tmp_path, "{ not json")
    assert result.returncode == 1
    assert "parse error" in result.stderr


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
            ["bash", str(GUARD), "HEAD"], cwd=repo, capture_output=True, text=True
        )
    finally:
        (repo / S).chmod(0o644)
    assert result.returncode == 1, "the staged grant was lost with the work-tree read"
    assert 'allow: "Bash(rm:*)"' in result.stderr
