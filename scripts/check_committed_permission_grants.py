#!/usr/bin/env python3
"""Fail a PR that widens what an agent may do without asking.

A committed permission grant is a standing auto-approve for every future agent
session in the repository. A prompt you answer once is a decision; a grant in a
tracked settings file is a policy, and it outlives whatever made it look
reasonable. Grants belong in untracked local config -- the `auto-chunk` skill
forbids committing one to obtain a tool a run needs, and this is the check that
makes that rule true rather than aspirational.

It is the deterministic floor under a *diff-only* security review, which sees a
settings file only when it is in the diff and cannot weigh a grant against a
base state it never read. There is no path-based skip: this runs on every PR.

WHAT IT COMPARES. Not "did the diff touch settings" but the union of entries
across every tracked `.claude/settings*.json` at <base> against the same at
HEAD, keyed by kind, value and the scope the file governs. Widening is reported
two ways:

    a GRANT is at HEAD that nothing at <base> covers;
    a RESTRICTION is at <base> that nothing at HEAD covers.

SCOPE. A settings file governs its own subtree, so an entry covers another when
the value matches and its scope is the same or an ancestor. Moving a grant to a
broader scope is therefore a new grant while narrowing it is not, and moving a
restriction outward is a tightening while moving it deeper is a weakening.

ORDERING. `deny` is stronger than `ask`, so a base `ask` is satisfied by either
at HEAD. Promoting one to the other is a security improvement, and a check that
failed a tightening would be ignored, which is worse than not running.

OVERRIDE. A weakening is overridable with ALLOW_PERMISSION_WEAKENING=1, because
a rule can go obsolete and has to be deletable, and setting that on the job is
itself a reviewable diff. An added grant is never overridable: it has no
legitimate in-repo form.

FAILS CLOSED, ASYMMETRICALLY. Input that cannot be read is an error, never a
pass -- a control reporting success on input it could not read is worse than no
control, because the green check is taken as evidence. But that applies at HEAD
only. An unreadable file at <base> is already on the main branch, and failing on
it would fail every PR including the one repairing it. So a base-side file that
cannot be read contributes nothing and warns, which stays conservative both
ways: no grant is hidden, and nothing can look weakened.

DELIBERATELY NOT CHECKED: a `hooks` block. Hooks execute automatically too, but
committing them is the supported way to configure a project rather than a way to
widen what an agent may approve, so flagging every one would bury the signal. If
that stops holding it wants its own guard, not a branch in this one.

Usage: check_committed_permission_grants.py <base-ref>
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import PurePosixPath

SETTINGS_RE = re.compile(r"(^|/)\.claude/settings[^/]*\.json$")
"""Any depth, not just the repo root: `packages/app/.claude/settings.json` is
live for anyone who opens Claude Code in that subdirectory."""

SAFE_DEFAULT_MODES = ("default", "plan")
"""The modes that grant nothing. An allowlist, not a blocklist, so a mode that
ships after this was written fails closed and gets looked at rather than being
permitted by an enumeration nobody remembered to update."""

GRANT = "grant"
RESTRICTION = "restriction"

# Which half each kind belongs to. Ten kinds, one table, so nothing downstream
# has to re-derive whether something grants or restricts.
KIND_HALF = {
    "allow": GRANT,
    "additionalDirectories": GRANT,
    "defaultMode": GRANT,
    "enableAllProjectMcpServers": GRANT,
    "enabledMcpjsonServers": GRANT,
    "deny": RESTRICTION,
    "ask": RESTRICTION,
    "plan": RESTRICTION,
    "disableBypassPermissionsMode": RESTRICTION,
    "disabledMcpjsonServers": RESTRICTION,
}

# The kinds read from a JSON array. `nested` says whether the key sits under
# `permissions` or beside it at the top level.
LIST_FIELDS = {
    "allow": True,
    "additionalDirectories": True,
    "deny": True,
    "ask": True,
    "enabledMcpjsonServers": False,
    "disabledMcpjsonServers": False,
}

# `plan` is tracked as its own restriction kind so it can be compared apart
# from the grant half of `defaultMode`, but it is the same settings key and must
# be reported under that name or the fixer is sent looking for a field that does
# not exist.
REPORT_AS = {"plan": "defaultMode"}

SATISFIED_BY = {
    "deny": ("deny",),
    "ask": ("ask", "deny"),  # a deny is stronger, so it satisfies an ask
    "plan": ("plan",),
    "disableBypassPermissionsMode": ("disableBypassPermissionsMode",),
    "disabledMcpjsonServers": ("disabledMcpjsonServers",),
}


class Unreadable(Exception):
    """A settings file whose contents this guard cannot judge."""


def write_err(text: str) -> None:
    """Write to stderr as bytes, so a path survives the trip.

    Paths are decoded with ``surrogateescape``, and printing one through
    stderr's ``backslashreplace`` turns it into `p\\udcf6ckages/...`: unreadable,
    and GitHub cannot anchor an annotation to it. Encoding back the same way
    restores the original bytes, which is what the shell predecessor emitted.
    """
    buffer = getattr(sys.stderr, "buffer", None)
    if buffer is None:  # a text-only stub
        sys.stderr.write(text)
        return
    # UTF-8 for the text, `surrogateescape` for the path bytes carried inside
    # it. The filesystem encoding can be ASCII under `LC_ALL=C`, and this
    # script's own messages contain em dashes, so encoding with it turned an
    # annotation into a UnicodeEncodeError traceback.
    buffer.write(text.encode("utf-8", errors="surrogateescape"))
    buffer.flush()


def note(severity: str, message: str) -> None:
    """Emit a workflow annotation.

    GitHub reads these off stderr, so a base-side problem must not use `error`
    or a passing run posts a red annotation anyway.
    """
    write_err(f"::{severity}::{message}\n")


def as_json(value: object) -> str:
    """One entry, always exactly one line, and always safe to print.

    ``ensure_ascii`` is on deliberately. A settings value may carry a lone
    surrogate through a ``\\udXXX`` escape, which no encoder can emit, so
    printing one raw killed the report mid-run. Escaping every non-ASCII
    character keeps the entry encodable whatever it holds, and shows the fixer
    the exact bytes rather than something a terminal may render ambiguously.
    Both sides of the comparison are escaped the same way, so nothing moves.
    """
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def entries_of(raw: bytes, label: str) -> set[tuple[str, str]]:
    """Every permission entry in one settings file, as `(kind, value)`.

    Raises :class:`Unreadable` with the message to report, distinguishing the
    three cases that need different fixes: no JSON at all, broken syntax, and a
    document whose field types are wrong.
    """
    # `utf-8-sig`, not `utf-8`: an editor may write a leading BOM, jq accepted
    # one, and rejecting it would fail every PR in that repo rather than only
    # the ones touching settings.
    #
    # Strict, though. `errors="replace"` repaired undecodable bytes into U+FFFD,
    # which collapses distinct values onto one key: a base grant and a different
    # head grant could both become the same string, and the change read as no
    # change. Silently repairing input is the fail-open this guard exists to
    # avoid.
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Unreadable(
            f"{label} is not valid UTF-8, so this guard cannot tell what it "
            f"permits: {exc}"
        ) from exc
    if not text.strip():
        raise Unreadable(
            f"{label} holds no JSON value at all (an empty file, or a truncated "
            "write), so this guard cannot tell what it permits."
        )
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise Unreadable(
            f"{label} is not valid JSON, so this guard cannot tell what it "
            f"permits: {exc}"
        ) from exc

    if doc is None:
        return set()

    shape = (
        f"{label} is valid JSON, but this guard could not read its permission "
        "fields. Check the value types: allow, deny, ask, additionalDirectories "
        "and enabledMcpjsonServers must be arrays, and defaultMode a string."
    )
    if not isinstance(doc, dict):
        raise Unreadable(shape)
    permissions = doc.get("permissions")
    if permissions is None:
        permissions = {}
    if not isinstance(permissions, dict):
        raise Unreadable(shape)

    found: set[tuple[str, str]] = set()
    for kind, nested in LIST_FIELDS.items():
        holder = permissions if nested else doc
        values = holder.get(kind)
        if values is None:
            continue
        if not isinstance(values, list):
            raise Unreadable(shape)
        found.update((kind, as_json(v)) for v in values)

    mode = permissions.get("defaultMode")
    if mode is not None:
        if not isinstance(mode, str):
            raise Unreadable(shape)
        if mode not in SAFE_DEFAULT_MODES:
            found.add(("defaultMode", as_json(mode)))
        if mode == "plan":
            # Stricter than the default it falls back to, so losing it widens.
            found.add(("plan", as_json(mode)))

    # `enableAllProjectMcpServers` is a sibling of `permissions`, not nested
    # under it. Anything but a literal false counts: `"true"` and `1` are not
    # booleans but are plainly not "off".
    for kind, nested in (
        ("enableAllProjectMcpServers", False),
        ("disableBypassPermissionsMode", True),
    ):
        holder = permissions if nested else doc
        value = holder.get(kind)
        if value is not None and value is not False:
            found.add((kind, as_json(value)))

    return found


def scope_of(path: str) -> str:
    """The subtree a settings file governs: everything before its `.claude/`."""
    head, sep, _ = path.rpartition("/.claude/")
    return head if sep else ""


def ancestors(scope: str) -> list[str]:
    """``scope`` and every directory above it, ending at the repo root."""
    out = [scope]
    while scope:
        scope = str(PurePosixPath(scope).parent)
        scope = "" if scope == "." else scope
        out.append(scope)
    return out


def uncovered(
    covering: set[tuple[str, str, str]],
    testing: set[tuple[str, str, str]],
    satisfied_by: dict[str, tuple[str, ...]] | None = None,
) -> list[tuple[str, str, str]]:
    """Entries in ``testing`` that nothing in ``covering`` covers.

    An entry covers another when the value matches and its scope is the same or
    an ancestor. ``satisfied_by`` lets a stronger kind stand in for a weaker
    one, which is what keeps an `ask` promoted to a `deny` from being reported.

    The scope stays on the result. Dropping it left the report unable to tell
    which file an added grant came from, so it annotated every settings file
    holding that value -- including one already on the base branch and outside
    the diff, told to remove a grant it had not added.
    """
    out = []
    for kind, scope, value in sorted(testing):
        kinds = (satisfied_by or {}).get(kind, (kind,))
        if not any(
            (k, parent, value) in covering for k in kinds for parent in ancestors(scope)
        ):
            out.append((kind, scope, value))
    return out


def git(*args: str, check: bool = True) -> bytes:
    """Run git from the repo root and return raw stdout."""
    result = subprocess.run(["git", *args], capture_output=True)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, args, result.stdout, result.stderr
        )
    return result.stdout


def settings_paths(listing: bytes) -> list[str]:
    """Tracked settings files out of a NUL-delimited git listing.

    NUL-delimited with `core.quotePath=false` throughout: git C-quotes any path
    holding a non-ASCII byte, a newline, a quote or a backslash, and a quoted
    path matched no pattern, so a grant inside one was invisible.
    """
    encoding = sys.getfilesystemencoding()
    paths = [
        chunk.decode(encoding, errors="surrogateescape")
        for chunk in listing.split(b"\0")
        if chunk
    ]
    return sorted(p for p in paths if SETTINGS_RE.search(p))


def head_content(path: str) -> bytes:
    """The HEAD copy: the work tree if readable, else the index.

    Reading only the work tree made this a permanent no-op under a sparse
    checkout excluding `.claude`, since base comes from git objects and head
    found nothing on disk. The index always holds the blob for a tracked path.
    """
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return git("show", f":{path}")


def collect(
    paths: list[str], read, label_for, on_unreadable
) -> set[tuple[str, str, str]]:
    """Read every settings file into a set of `(kind, scope, value)`."""
    found: set[tuple[str, str, str]] = set()
    for path in paths:
        try:
            raw = read(path)
        except (subprocess.CalledProcessError, OSError) as exc:
            on_unreadable(path, exc)
            continue
        try:
            entries = entries_of(raw, label_for(path))
        except Unreadable as exc:
            on_unreadable(path, exc)
            continue
        scope = scope_of(path)
        found.update((kind, scope, value) for kind, value in entries)
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: check_committed_permission_grants.py <base-ref>",
            file=sys.stderr,
        )
        return 2
    base = argv[1]

    # Run from the repo root, always: `git ls-tree -r` and `git ls-files` are
    # both scoped to the current directory, so invoking this from a
    # subdirectory reported a clean repo while a grant sat in the root file.
    try:
        # `surrogateescape` like every other path here: a checkout whose own
        # directory name is not valid UTF-8 would otherwise raise past this
        # handler and die with a traceback instead of the annotation. The chdir
        # is inside the block for the same reason -- an empty toplevel makes it
        # raise, and that is this failure, not an unhandled one.
        # `rstrip("\n")`, not `strip()`: a directory name may legitimately end
        # in a space, and trimming it made `chdir` fail on a repo the guard was
        # sitting inside.
        root = (
            git("rev-parse", "--show-toplevel")
            .decode(sys.getfilesystemencoding(), errors="surrogateescape")
            .rstrip("\n")
        )
        if not root:
            raise OSError("git reported no work-tree root")
        os.chdir(root)
    except (subprocess.CalledProcessError, OSError):
        note(
            "error",
            "not inside a git work tree, so this guard cannot enumerate "
            "anything. Refusing to report a repo unchanged that it could not "
            "inspect.",
        )
        return 1

    quiet = ("-c", "core.quotePath=false")
    try:
        base_listing = git(*quiet, "ls-tree", "-r", "-z", "--name-only", base)
    except (subprocess.CalledProcessError, OSError):
        note(
            "error",
            f"could not list tracked files at {base} (base-side enumeration); "
            "this guard will not report a repo unchanged that it could not "
            "enumerate.",
        )
        return 1

    def base_unreadable(path: str, exc: object) -> None:
        if isinstance(exc, Unreadable):
            note("warning", str(exc))
        note(
            "warning",
            f"{path} is already unreadable at {base}, so it is treated as "
            "permitting nothing: every grant in this PR's copy will read as "
            "new, and nothing it restricted can look weakened. Repair it on "
            "the base branch.",
        )

    base_entries = collect(
        settings_paths(base_listing),
        lambda p: git("show", f"{base}:{p}"),
        lambda p: f"{p} (at {base})",
        base_unreadable,
    )

    try:
        head_listing = git(*quiet, "ls-files", "-z")
    except (subprocess.CalledProcessError, OSError):
        note(
            "error",
            "could not list tracked files in the work tree (head-side "
            "enumeration); this guard will not report a repo unchanged that it "
            "could not enumerate.",
        )
        return 1

    head_paths = settings_paths(head_listing)

    def head_unreadable(path: str, exc: object) -> None:
        if isinstance(exc, Unreadable):
            note("error", str(exc))
        else:
            note(
                "error",
                f"{path} is tracked but its content could not be read from the "
                "work tree or the index, so this guard cannot tell what it "
                "permits.",
            )
        raise SystemExit(1)

    head_entries = collect(head_paths, head_content, lambda p: p, head_unreadable)

    def half(entries, which):
        return {e for e in entries if KIND_HALF[e[0]] == which}

    added = uncovered(half(base_entries, GRANT), half(head_entries, GRANT))
    weakened = uncovered(
        half(head_entries, RESTRICTION),
        half(base_entries, RESTRICTION),
        SATISFIED_BY,
    )

    if not added and not weakened:
        print(
            "OK: no permission grant added and no restriction weakened across "
            "tracked .claude/settings*.json."
        )
        return 0

    if added:
        wanted = set(added)
        for path in head_paths:
            try:
                entries = entries_of(head_content(path), path)
            except (Unreadable, subprocess.CalledProcessError, OSError):
                continue
            scope = scope_of(path)
            here = sorted(
                (kind, value)
                for kind, value in entries
                if (kind, scope, value) in wanted
            )
            if here:
                note(
                    f"error file={path}",
                    f"New permission grant(s) committed to {path} — move them "
                    "to untracked local config (AGENTS.md: never commit a "
                    "permission grant).",
                )
                for kind, value in here:
                    write_err(f"  {REPORT_AS.get(kind, kind)}: {value}\n")

    if weakened:
        listing = "\n".join(
            f"  {REPORT_AS.get(kind, kind)}: {value}"
            for kind, _scope, value in weakened
        )
        if os.environ.get("ALLOW_PERMISSION_WEAKENING") == "1":
            note(
                "warning",
                f"This PR weakens a restriction that {base} had, allowed by "
                "ALLOW_PERMISSION_WEAKENING=1.",
            )
            write_err(listing + "\n")
            weakened = []
        else:
            note(
                "error",
                f"This PR weakens a restriction that {base} had, which widens "
                "what an agent may do without asking just as an added grant "
                "would. Restore it, or — if the removal is the point — set "
                "ALLOW_PERMISSION_WEAKENING=1 on this job, which is itself a "
                "reviewable change. (Promoting an `ask` to a `deny` is a "
                "tightening and is not reported.)",
            )
            write_err(listing + "\n")

    if added or weakened:
        return 1
    print(
        "OK: no permission grant added, and the restriction change is allowed "
        "by ALLOW_PERMISSION_WEAKENING=1."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
