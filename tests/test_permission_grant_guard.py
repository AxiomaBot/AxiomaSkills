"""Tests for the committed-permission-grant guard.

The guard is the deterministic floor under a diff-only security review, and
`workflow init` ships a copy of it into every project this plugin scaffolds --
so a hole here is a hole in every consumer at once, and silently. Each test
builds a two-commit repository, puts exactly one thing in the head state, and
asserts the guard's verdict.

Only `permissions.allow` was ever checked. `defaultMode` and
`additionalDirectories` grant strictly more and went through untouched, which
is the gap these tests pin shut.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
GUARD = PLUGIN / "scripts" / "check_committed_permission_grants.sh"

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
    assert "allow: Bash(rm:*)" in result.stderr
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
    assert f"defaultMode: {mode}" in result.stderr


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
    assert "defaultMode: yoloMode2030" in result.stderr


def test_a_granting_mode_already_at_base_is_not_newly_introduced(tmp_path: Path):
    settings = {"permissions": {"defaultMode": "bypassPermissions"}}
    assert run_guard(tmp_path, {S: settings}, {S: settings}).returncode == 0


# --- additionalDirectories: the other gap


def test_a_new_additional_directory_fails(tmp_path: Path):
    result = run_guard(
        tmp_path, {}, {S: {"permissions": {"additionalDirectories": ["/etc"]}}}
    )
    assert result.returncode == 1
    assert "additionalDirectories: /etc" in result.stderr


def test_an_additional_directory_already_at_base_passes(tmp_path: Path):
    settings = {"permissions": {"additionalDirectories": ["../sibling"]}}
    assert run_guard(tmp_path, {S: settings}, {S: settings}).returncode == 0


# --- shared behaviour


def test_all_three_kinds_are_reported_together(tmp_path: Path):
    result = run_guard(
        tmp_path,
        {},
        {
            S: {
                "permissions": {
                    "allow": ["Bash(curl:*)"],
                    "additionalDirectories": ["/srv"],
                    "defaultMode": "bypassPermissions",
                }
            }
        },
    )
    assert result.returncode == 1
    for expected in (
        "allow: Bash(curl:*)",
        "additionalDirectories: /srv",
        "defaultMode: bypassPermissions",
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


def test_unparseable_json_does_not_crash_the_guard(tmp_path: Path):
    repo = tmp_path / "repo"
    result = run_guard(tmp_path, {}, {S: {"permissions": {"allow": []}}})
    assert result.returncode == 0
    (repo / S).write_text("{ not json", encoding="utf-8")
    _git(repo, "add", "-A")
    again = subprocess.run(
        ["bash", str(GUARD), "HEAD"], cwd=repo, capture_output=True, text=True
    )
    assert again.returncode in (0, 1), again.stderr
