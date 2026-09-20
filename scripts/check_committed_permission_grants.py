#!/usr/bin/env python3
"""Fail a PR that commits a permission grant to a tracked settings file.

A grant in a tracked `.claude/settings*.json` is a standing auto-approve for
every future agent session in the repository. A prompt you answer once is a
decision; a committed grant is a policy, and it outlives whatever made it look
reasonable. Grants belong in untracked local config, which is why the
`auto-chunk` skill forbids committing one to obtain a tool a run needs. This is
the check that makes that rule true rather than aspirational.

It is an ABSOLUTE check, not a comparison with the base branch. That is the
whole design, and it is deliberately narrower than it once was:

  * there is no base/head diff, so a grant already on the main branch fails
    too, rather than passing forever because both sides agree;
  * there is nothing to say about a grant being moved, renamed, split across
    files, or scoped to a subdirectory -- any tracked settings file holding one
    fails, wherever it sits;
  * removing a `deny` or `ask` entry is NOT a finding. Weakening detection was
    the single largest source of complexity here and it earned none of it: in
    these repositories such a removal is a visible diff that a human reads.

FIVE keys grant, and `permissions.allow` is the narrowest of them:

    allow                       one tool pattern pre-approved.
    additionalDirectories       filesystem reach outside the project.
    defaultMode                 the blanket setting. `bypassPermissions`,
                                `dontAsk` and `acceptEdits` each approve a whole
                                class of action with no allow entry at all.
    enableAllProjectMcpServers  a sibling of `permissions`, not nested under it,
                                auto-approving every MCP server the project's
                                `.mcp.json` declares.
    enabledMcpjsonServers       the same, one named server at a time.

`defaultMode` is tested against an ALLOWLIST of the modes that grant nothing, so
a mode shipped after this was written fails closed and gets looked at rather
than being permitted by an enumeration nobody updated.

DELIBERATELY NOT CHECKED: a `hooks` block. Hooks execute automatically too, but
committing them is the supported way to configure a project rather than a way to
widen what an agent may approve, so flagging every one would bury the signal.

IT FAILS CLOSED. A settings file it cannot read is an error, never a pass: a
control that reports success on input it could not parse is worse than no
control, because the green check is taken as evidence.

Usage: check_committed_permission_grants.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

SETTINGS_RE = re.compile(r"(^|/)\.claude/settings[^/]*\.json$")
"""Any depth, not just the repo root: `packages/app/.claude/settings.json` is
live for anyone who opens Claude Code in that subdirectory."""

SAFE_DEFAULT_MODES = ("default", "plan")
"""The modes that grant nothing: `default` prompts as usual, `plan` is stricter."""

LIST_KEYS = {
    "allow": True,  # True: nested under `permissions`
    "additionalDirectories": True,
    "enabledMcpjsonServers": False,
}


class Unreadable(Exception):
    """A settings file whose contents this guard cannot judge."""


def write_err(text: str) -> None:
    """Write to stderr as bytes, so an odd path survives the trip.

    Paths are decoded with `surrogateescape`; printing one through stderr's
    `backslashreplace` mangles it into something GitHub cannot anchor an
    annotation to. Encoding back restores the original bytes.
    """
    buffer = getattr(sys.stderr, "buffer", None)
    if buffer is None:
        sys.stderr.write(text)
        return
    buffer.write(text.encode("utf-8", errors="surrogateescape"))
    buffer.flush()


def as_json(value: object) -> str:
    """One grant, always one line, and always safe to print.

    `ensure_ascii` is on deliberately: a value may carry a lone surrogate
    through a `\\udXXX` escape, which no encoder can emit.
    """
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def grants_in(raw: bytes, label: str) -> list[str]:
    """Every grant in one settings file, as `<key>: <value>` strings.

    Raises :class:`Unreadable` with the message to report, separating the three
    cases that need different fixes: no JSON at all, broken syntax, and a
    document whose field types are wrong.
    """
    if not raw.strip():
        raise Unreadable(
            f"{label} holds no JSON value at all (an empty file, or a truncated "
            "write), so this guard cannot tell what it permits."
        )
    try:
        # `utf-8-sig` because an editor may write a BOM; strict because
        # `errors="replace"` would silently repair bytes into U+FFFD.
        doc = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise Unreadable(
            f"{label} is not valid UTF-8, so this guard cannot tell what it "
            f"permits: {exc}"
        ) from exc
    except ValueError as exc:
        raise Unreadable(
            f"{label} is not valid JSON, so this guard cannot tell what it "
            f"permits: {exc}"
        ) from exc

    if doc is None:
        return []

    shape = (
        f"{label} is valid JSON, but this guard could not read its permission "
        "fields. Check the value types: allow, additionalDirectories and "
        "enabledMcpjsonServers must be arrays, and defaultMode a string."
    )
    if not isinstance(doc, dict):
        raise Unreadable(shape)
    permissions = doc.get("permissions") or {}
    if not isinstance(permissions, dict):
        raise Unreadable(shape)

    found = []
    for key, nested in LIST_KEYS.items():
        values = (permissions if nested else doc).get(key)
        if values is None:
            continue
        if not isinstance(values, list):
            raise Unreadable(shape)
        found += [f"{key}: {as_json(v)}" for v in values]

    mode = permissions.get("defaultMode")
    if mode is not None:
        if not isinstance(mode, str):
            raise Unreadable(shape)
        if mode not in SAFE_DEFAULT_MODES:
            found.append(f"defaultMode: {as_json(mode)}")

    # Anything but a literal false counts: `"true"` and `1` are not booleans but
    # are plainly not "off".
    enable_all = doc.get("enableAllProjectMcpServers")
    if enable_all is not None and enable_all is not False:
        found.append(f"enableAllProjectMcpServers: {as_json(enable_all)}")

    return sorted(found)


def tracked_settings() -> list[str]:
    """Every tracked `.claude/settings*.json`, from the repo root.

    NUL-delimited with `core.quotePath=false`: git C-quotes a path holding a
    non-ASCII byte, a newline, a quote or a backslash, and a quoted path matches
    no pattern, so a grant inside one would be invisible.
    """
    listing = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files", "-z"],
        capture_output=True,
        check=True,
    ).stdout
    encoding = sys.getfilesystemencoding()
    paths = (
        chunk.decode(encoding, errors="surrogateescape")
        for chunk in listing.split(b"\0")
        if chunk
    )
    return sorted(p for p in paths if SETTINGS_RE.search(p))


def content_of(path: str) -> bytes:
    """The work-tree copy if readable, else the index.

    A tracked file can be absent from disk under a sparse checkout, and reading
    only the work tree would make this guard a silent no-op there.
    """
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return subprocess.run(
            ["git", "show", f":{path}"], capture_output=True, check=True
        ).stdout


def main() -> int:
    # `git ls-files` is scoped to the current directory, so run from the root.
    # `rstrip("\n")` not `strip()`: a directory name may end in a space.
    try:
        root = (
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                check=True,
            )
            .stdout.decode(sys.getfilesystemencoding(), errors="surrogateescape")
            .rstrip("\n")
        )
        if not root:
            raise OSError("git reported no work-tree root")
        os.chdir(root)
        paths = tracked_settings()
    except (subprocess.CalledProcessError, OSError) as exc:
        write_err(
            "::error::could not enumerate tracked files, so this guard will not "
            f"report a repo grant-free that it could not inspect: {exc}\n"
        )
        return 1

    failed = False
    for path in paths:
        try:
            found = grants_in(content_of(path), path)
        except Unreadable as exc:
            write_err(f"::error file={path}::{exc}\n")
            failed = True
            continue
        except (subprocess.CalledProcessError, OSError):
            write_err(
                f"::error file={path}::{path} is tracked but its content could "
                "not be read from the work tree or the index, so this guard "
                "cannot tell what it permits.\n"
            )
            failed = True
            continue
        if found:
            write_err(
                f"::error file={path}::Permission grant(s) committed to {path} "
                "— move them to untracked local config (AGENTS.md: never commit "
                "a permission grant).\n"
            )
            for grant in found:
                write_err(f"  {grant}\n")
            failed = True

    if failed:
        return 1
    print(f"OK: no permission grant in {len(paths)} tracked settings file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
