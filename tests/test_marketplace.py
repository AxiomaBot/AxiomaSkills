"""Pin the multi-plugin repo layout.

This repo is a marketplace that serves one plugin per directory under
`plugins/`. Adding a second plugin should be a directory and one marketplace
entry, not a scavenger hunt through the README for what else needs touching --
so the rules that make that true are checked here rather than remembered.

The layout matters beyond tidiness. A marketplace entry whose source does not
name a real directory is an install that resolves to nothing, and there is no
commit pin to fall back on: a plugin entry's source can address a repo root but
not a subdirectory, so serving several plugins from one repo rules pinning out
entirely. The marketplace listing is the only route in, which is why these
tests check it rather than trusting a README to stay true.
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
PLUGINS_DIR = REPO / "plugins"

MANIFEST_KEYS = ("name", "version", "description")


def _marketplace() -> dict:
    return json.loads(MARKETPLACE.read_text(encoding="utf-8"))


def _plugin_dirs() -> list[Path]:
    return sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir())


def _manifest(plugin_dir: Path) -> dict:
    return json.loads(
        (plugin_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )


def test_every_plugin_directory_has_a_manifest():
    for plugin_dir in _plugin_dirs():
        manifest = plugin_dir / ".claude-plugin" / "plugin.json"
        assert manifest.exists(), f"{plugin_dir.name} has no .claude-plugin/plugin.json"


@pytest.mark.parametrize("key", MANIFEST_KEYS)
def test_every_manifest_carries_the_keys_that_matter(key: str):
    """`version` especially: the plugin cache is keyed by it, so a plugin
    without one can never be updated on a machine that already has it."""
    for plugin_dir in _plugin_dirs():
        manifest = _manifest(plugin_dir)
        assert key in manifest, f"{plugin_dir.name}'s manifest lacks `{key}`"
        assert str(manifest[key]).strip(), f"{plugin_dir.name}'s `{key}` is empty"


def test_a_manifest_name_matches_its_directory():
    """A plugin is addressed by manifest name but found by path.

    A marketplace entry names `./plugins/<dir>` while everything downstream --
    `enabledPlugins`, the `<plugin>:<skill>` namespace, `claude plugin install`
    -- uses the manifest's `name`. A mismatch makes those two disagree with no
    error at either end.
    """
    for plugin_dir in _plugin_dirs():
        assert _manifest(plugin_dir)["name"] == plugin_dir.name, (
            f"{plugin_dir.name}/ declares the name "
            f"`{_manifest(plugin_dir)['name']}`; they must match"
        )


def test_the_marketplace_lists_exactly_the_plugins_that_exist():
    listed = {entry["name"] for entry in _marketplace()["plugins"]}
    on_disk = {p.name for p in _plugin_dirs()}
    assert listed == on_disk, (
        f"marketplace lists {sorted(listed)} but plugins/ holds "
        f"{sorted(on_disk)}; a new plugin needs both"
    )


def test_every_entry_points_at_its_own_directory():
    """A relative source must start with `./` and name the real directory."""
    for entry in _marketplace()["plugins"]:
        source = entry["source"]
        assert isinstance(source, str), (
            f"{entry['name']}: this repo serves its own plugins by relative "
            "path, so the source should be a string like ./plugins/<name>"
        )
        assert source == f"./plugins/{entry['name']}", (
            f"{entry['name']}: source is `{source}`, expected "
            f"`./plugins/{entry['name']}`"
        )
        assert (REPO / source).is_dir(), f"{source} is not a directory"


def test_every_entry_carries_a_description():
    """The marketplace listing is how someone decides whether to install."""
    for entry in _marketplace()["plugins"]:
        assert entry.get("description", "").strip(), (
            f"{entry['name']} has no description in the marketplace"
        )


def test_the_marketplace_description_matches_the_plugin_manifest():
    """The same sentence lives in two files, so pin it rather than trust it.

    A plugin's own manifest describes it, and the marketplace repeats that for
    the listing. Nothing in Claude Code derives one from the other, so an edit
    to a plugin's description silently leaves the listing showing the old one
    -- and the listing is what someone reads when deciding to install.
    """
    manifests = {p.name: _manifest(p)["description"] for p in _plugin_dirs()}
    for entry in _marketplace()["plugins"]:
        assert entry["description"] == manifests[entry["name"]], (
            f"{entry['name']}: the marketplace description and "
            f"plugins/{entry['name']}/.claude-plugin/plugin.json disagree; "
            "edit both"
        )


def test_no_plugin_manifest_sits_at_the_repo_root():
    """The old single-plugin-at-root layout must not creep back.

    Both shapes at once would be ambiguous: the root manifest would make the
    whole repo a plugin, shipping `tests/`, `fixture/` and every other plugin
    inside it.
    """
    assert not (REPO / ".claude-plugin" / "plugin.json").exists(), (
        "a plugin.json at the repo root reintroduces the single-plugin layout; "
        "plugins live in plugins/<name>/"
    )


# Never legitimate at a plugin's top level.
#
# `scripts` is deliberately NOT here: a plugin with hooks conventionally ships
# `scripts/` and references it as `${CLAUDE_PLUGIN_ROOT}/scripts/...`, so
# forbidding it would fail CI on a plugin the root README invites. This repo's
# own CI guard is covered instead by the byte-for-byte pin in
# `test_bundled_copies.py`, which fails if the root copy moves.
DEV_ONLY_AT_TOP = frozenset({"tests", "fixture", "pyproject.toml", ".github"})

# Never legitimate at any depth inside a plugin.
DEV_ONLY_ANYWHERE = frozenset({"tests", "fixture"})


def test_a_plugin_ships_only_what_installs():
    """Development scaffolding stays at the repo root, out of the install.

    Everything in a plugin directory is copied to every consumer, so the
    fixture project, the test suite and this repo's own CI guards do not
    belong inside one.
    """
    for plugin_dir in _plugin_dirs():
        present = {p.name for p in plugin_dir.iterdir()} & DEV_ONLY_AT_TOP
        assert not present, (
            f"{plugin_dir.name}/ contains {sorted(present)}, which is "
            "development scaffolding and belongs at the repo root"
        )


def test_no_scaffolding_hides_deeper_in_a_plugin():
    """A top-level check alone would pass on `plugins/foo/bar/tests/`.

    Only names with no legitimate home at any depth are checked. `scripts` is
    not among them: a plugin's bundled scripts sit at `skills/<name>/scripts/`
    and its hook scripts at `scripts/`, and both ship on purpose.
    """
    for plugin_dir in _plugin_dirs():
        nested = sorted(
            str(p.relative_to(plugin_dir))
            for p in plugin_dir.rglob("*")
            if p.is_dir() and p.name in DEV_ONLY_ANYWHERE
        )
        assert not nested, (
            f"{plugin_dir.name}/ carries {nested} inside it; development "
            "scaffolding belongs at the repo root, not in the install"
        )
