#!/usr/bin/env python3
"""Build the compact PR-review context that both reviewer subagents read.

The `pr-review` skill (`skills/pr-review/SKILL.md`, in the `agentic-workflow`
plugin) runs this instead of assembling the diffs by prompt: the allocation
below is the part that has to be exact.

For each variant it writes two files into ``<out-dir>/<variant>/``:

``changed-files.txt``
    ``git diff --name-status`` over the PR range -- every changed file, never
    abridged, so a reviewer is never misled about the PR's real scope.
``pr.diff``
    one entry per changed file in alphabetical order, each file's share of the
    variant's total cap decided by max-min fair allocation.

Four properties, all held by :func:`allocate`:

* the allocated total never exceeds the cap (the written total matches it
  except for the markers noted on :func:`fit` and ``UNAVAILABLE_MARKER``);
* no file is truncated while budget goes unspent;
* no file is ever dropped -- every file gets at least ``cap / file count``;
* it is order-independent, so alphabetical order is layout, not priority.

Usage::

    python scripts/review_context.py --out-dir <dir outside the worktree>
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROSE_SUFFIX = ".md"
PROSE_UNIFIED = 3
"""Context lines for prose.

Wide context earns its budget on code -- a reviewer judging a changed function
needs the surrounding guards and call sites. On markdown it buys almost
nothing, and at ``--unified=80`` a one-line edit drags in 160 lines of
neighbouring paragraphs.
"""


@dataclass(frozen=True)
class Variant:
    """One reviewer's context budget."""

    name: str
    code_unified: int
    total_cap: int


VARIANTS = (
    Variant("quality", code_unified=80, total_cap=300_000),
    Variant("security", code_unified=120, total_cap=400_000),
)

EXCLUDES = (
    ":(exclude)*.ipynb",
    ":(exclude)dist/**",
    ":(exclude)build/**",
    ":(exclude)coverage/**",
)
"""Only genuine build/output artifacts.

Two inclusions are deliberate, not oversights. **Lockfiles** stay in, because
a dependency change is security-relevant and allocation bounds any one of them
without starving the rest. **The archive files** under ``docs/archive/`` stay
in too: excluding them was tried and reverted, because a ``/handoff`` reopen
legitimately deletes a section from an archive and that is exactly the edit
worth a reviewer's eyes. This plugin's own repo pins both in CI.
"""

OMIT_PATTERNS = (
    # The only path this plugin's own layout ever produces.
    "docs/features/*/chunks/*.md",
    # Legacy, from the project this plugin was extracted from -- see below.
    "docs/audits/**/*.md",
    "docs/plan.md",
)
"""Process artifacts: listed in ``changed-files.txt``, never expanded.

A chunk file is the build's own *input specification* -- its goal, assumptions
and rationale are exactly what spawning fresh reviewers withholds, so shipping
it inside ``pr.diff`` would hand back what the prompt is written to keep out.
Scoped to markdown deliberately: a script or config that ever lands under one
of these paths stays fully in the diff like any other changed file.

**The last two patterns are legacy and match nothing this plugin creates.** No
skill writes to either path and ``workflow init`` scaffolds neither, so a
project set up from this plugin will never hit them. They are the pre-extraction
layout of the project this workflow came out of: ``docs/plan.md`` was the single
chunk file before per-feature folders, and ``docs/audits/`` held auditors' prose
about the workflow rather than about the change under review.

They stay because the cost is asymmetric. A pattern that matches nothing costs a
consuming project nothing, while dropping one that still matches somewhere would
quietly start feeding a reviewer the author's own rationale -- the exact
property this module exists to hold. Drop them once no repository using this
plugin has a file at either path; note that a migration moves both under
``docs/archive/`` with ``git mv``, and that directory is deliberately *not*
omitted (see :data:`EXCLUDES`).
"""

OUTPUT_FILES = {"changed-files.txt", "pr.diff"}
"""The only files this script writes into a variant directory."""

TRUNCATION_MARKER = (
    "[DIFF TRUNCATED for {path} at {boundary} boundary: review may be incomplete]\n"
)
UNAVAILABLE_MARKER = (
    "[DIFF TRUNCATED for {path}: git produced no diff for this changed path, "
    "so none of it was reviewed]\n"
)
"""Emitted when a changed path yields an empty diff.

`git diff` never returns nothing for a path in the range, so an empty result
means the path we reconstructed is not the path git changed -- a filename
whose bytes do not survive decoding is the realistic cause now that the paths
come from ``-z`` output. Writing zero bytes would break "no file is ever
dropped" silently, so it counts as truncation and shows up in the summary
`/pr-review` reads. It bypasses the file's share: naming a path beats silence,
and one marker cannot meaningfully tax the pool.
"""
OMISSION_MARKER = (
    "[PROCESS ARTIFACT — {path} deliberately not shown; "
    "see review_context.py → OMIT_PATTERNS]\n"
)
"""The two markers deliberately share no token, so a scan for truncation can
never match an omission."""


GIT_TIMEOUT_S = 120


def _run(args: list[str], repo: Path) -> bytes:
    """Run a git command in ``repo`` and return its raw stdout."""
    result = subprocess.run(args, cwd=repo, capture_output=True, timeout=GIT_TIMEOUT_S)
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"{' '.join(args)} failed ({result.returncode}): {detail}")
    return result.stdout


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a path glob where ``*`` stops at ``/`` and ``**/`` spans dirs."""
    out = ["(?s:"]
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append(")\\Z")
    return re.compile("".join(out))


_OMIT_REGEXES = tuple(_glob_to_regex(p) for p in OMIT_PATTERNS)


def is_process_artifact(path: str) -> bool:
    """True if ``path`` is listed but never expanded (see OMIT_PATTERNS)."""
    return any(rx.match(path) for rx in _OMIT_REGEXES)


def unified_for(path: str, variant: Variant) -> int:
    """Context lines for ``path``: the prose value for markdown, else code."""
    return PROSE_UNIFIED if path.endswith(PROSE_SUFFIX) else variant.code_unified


def worktree_root(path: Path) -> Path:
    """The repository root for ``path``.

    Everything downstream is repo-root-relative: ``--name-status`` paths are,
    and a pathspec is cwd-relative unless it carries ``:(top)``. Resolving the
    root once means a run from a subdirectory behaves identically instead of
    pairing root-relative paths with subdirectory-relative excludes.
    """
    return Path(_run(["git", "rev-parse", "--show-toplevel"], path).decode().strip())


def merge_base(repo: Path, base_ref: str = "origin/main") -> str:
    """The merge base of ``base_ref`` and HEAD -- the PR range's start."""
    return _run(["git", "merge-base", base_ref, "HEAD"], repo).decode().strip()


def name_status(repo: Path, base: str) -> bytes:
    """Raw ``--name-status`` output for the PR range (the changed-files file)."""
    return _run(
        [
            "git",
            "-c",
            "core.quotepath=false",
            "diff",
            "--name-status",
            f"{base}...HEAD",
            "--",
            *EXCLUDES,
        ],
        repo,
    )


def name_status_z(repo: Path, base: str) -> bytes:
    """``--name-status -z`` for the same range.

    ``-z`` is what makes the paths parseable: in normal output git c-quotes any
    path containing a tab, newline or quote, and a reconstructed quoted path
    matches nothing when handed back as a pathspec. The text form above stays
    the one written to ``changed-files.txt``, so a reviewer reads git's own
    rendering.
    """
    return _run(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            f"{base}...HEAD",
            "--",
            *EXCLUDES,
        ],
        repo,
    )


def changed_paths(name_status_z_out: bytes) -> list[str]:
    """Every changed path in the range, sorted; renames report their new path.

    Reads NUL-delimited fields: a status, then one path, except an R/C status
    which is followed by the old path and then the new one. The new path is the
    one to diff by; ``changed-files.txt`` keeps the full R row, so a rename's
    old path is never lost to the reviewer.
    """
    fields = name_status_z_out.split(b"\0")
    paths = set()
    i = 0
    while i < len(fields):
        status = fields[i]
        if not status:
            i += 1
            continue
        wanted = i + 2 if status[:1] in (b"R", b"C") else i + 1
        if wanted >= len(fields):
            break
        paths.add(fields[wanted].decode(errors="replace"))
        i = wanted + 1
    return sorted(paths)


def file_diff(repo: Path, base: str, path: str, unified: int) -> bytes:
    """The full diff for one path at ``unified`` lines of context."""
    return _run(
        [
            "git",
            "diff",
            f"--unified={unified}",
            "--no-ext-diff",
            f"{base}...HEAD",
            "--",
            # :(top) because a pathspec is cwd-relative but --name-status
            # paths are repo-root-relative; :(literal) so a filename
            # containing glob characters is a filename.
            f":(top,literal){path}",
        ],
        repo,
    )


def allocate(sizes: dict[str, int], cap: int) -> dict[str, int]:
    """Max-min fair allocation of ``cap`` bytes over ``sizes``.

    Every file that fits the current equal share is written in full; the budget
    it leaves unspent raises the share for the rest. When nothing fits, the
    remaining files split what is left equally.
    """
    pool = dict(sizes)
    shares: dict[str, int] = {}
    budget = cap
    while pool:
        share = budget // len(pool)
        fits = {path: size for path, size in pool.items() if size <= share}
        if not fits:
            return shares | dict.fromkeys(pool, share)
        for path, size in fits.items():
            shares[path] = size
            budget -= size
            del pool[path]
    return shares


def _utf8_safe_end(content: bytes, end: int) -> int:
    """The largest cut at or below ``end`` that does not split a character.

    A cut inside a multi-byte character leaves ``pr.diff`` undecodable from
    that point, which costs the reviewer the rest of the file rather than the
    few bytes saved. Anything that is not UTF-8-shaped is left alone.
    """
    if end >= len(content) or end <= 0:
        return end
    start = end
    while start > 0 and 0x80 <= content[start - 1] < 0xC0:
        start -= 1
    if start == 0 or content[start - 1] < 0x80:
        return end
    lead = content[start - 1]
    width = 2 if lead < 0xE0 else 3 if lead < 0xF0 else 4
    char_end = start - 1 + width
    return char_end if char_end <= end else start - 1


def _retains_hunk_body(prefix: bytes) -> bool:
    """True if ``prefix`` keeps at least one line of an actual hunk.

    A git diff opens with ``diff --git``, mode and ``---``/``+++`` lines, so a
    line-boundary cut can always find a boundary and still retain nothing but
    that preamble. This is what distinguishes "truncated with content" from
    "truncated to a header".
    """
    after_hunk_header = prefix.split(b"\n@@", 1)
    if len(after_hunk_header) < 2:
        return False
    body = after_hunk_header[1].split(b"\n", 1)
    return len(body) > 1 and bool(body[1].strip())


def fit(content: bytes, share: int, path: str) -> tuple[bytes, str | None]:
    """Cut ``content`` to ``share`` bytes, marker included.

    Returns the bytes to write and the boundary used, or ``None`` when the
    content fit in full. Cuts at a line boundary; falls back to a byte boundary
    when not even one whole line fits, so an oversized single diff line (a
    minified asset, the committed Tailwind build) can never leave a changed
    file at zero bytes, and never at a header with none of the change. The
    marker counts inside the share, so the written file stays within it --
    except when the share is smaller than the marker itself, where naming the
    file beats silence.
    """
    if len(content) <= share:
        return content, None

    def marker_for(boundary: str) -> bytes:
        return TRUNCATION_MARKER.format(path=path, boundary=boundary).encode()

    line_marker = marker_for("line")
    if share - len(line_marker) <= 0:
        # Share too small for content and marker both: the marker alone wins,
        # so the reviewer still learns the file exists and was not reviewed.
        # This is the one case where a file exceeds its share.
        return marker_for("byte"), "byte"
    cut = content.rfind(b"\n", 0, share - len(line_marker))
    if cut >= 0 and _retains_hunk_body(content[: cut + 1]):
        return content[: cut + 1] + line_marker, "line"
    # Either no whole line fits, or the only whole lines that do are the diff
    # header -- which tells a reviewer nothing changed-files.txt hasn't already
    # said. Cut mid-line instead so some of the change itself is reviewable,
    # sized against the byte marker, the one actually written.
    byte_marker = marker_for("byte")
    end = _utf8_safe_end(content, max(0, share - len(byte_marker)))
    return content[:end] + byte_marker, "byte"


@dataclass
class VariantResult:
    """What one variant's context came out as."""

    variant: Variant
    directory: Path
    total: int
    file_count: int
    truncated: list[str]
    omitted: list[str]


def clear_variant_dir(directory: Path) -> None:
    """Remove a variant directory, but only if this script wrote it.

    A stale ``pr.diff`` is a context anchored to a different head, so it must
    never survive into a run -- but a mistyped ``--out-dir`` must not delete
    someone's unrelated ``quality/`` either, so only a directory holding
    nothing outside :data:`OUTPUT_FILES` is removed.
    """
    if not directory.exists():
        return
    extra = {p.name for p in directory.iterdir()} - OUTPUT_FILES
    if extra:
        raise RuntimeError(
            f"{directory} holds files this script did not write "
            f"({', '.join(sorted(extra))}); point --out-dir at a directory "
            "dedicated to review contexts"
        )
    shutil.rmtree(directory)


def build_variant(
    repo: Path,
    base: str,
    variant: Variant,
    out_dir: Path,
    status: bytes,
    paths_status: bytes,
) -> VariantResult:
    """Write one variant's ``changed-files.txt`` and ``pr.diff``.

    ``status`` is the text ``--name-status`` output written verbatim to
    ``changed-files.txt``; ``paths_status`` is the ``-z`` form the paths are
    parsed from. Both are required deliberately: passing the text form as
    ``paths_status`` parses to no paths at all, which would write an empty
    ``pr.diff`` and silently defeat "no file is ever dropped".
    """
    directory = out_dir / variant.name
    # Rebuilt from scratch: a surviving pr.diff from an earlier run would be a
    # context anchored to a different head. chmod explicitly, since mkdir's
    # mode applies to neither an existing directory nor the parents.
    clear_variant_dir(directory)
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)

    paths = changed_paths(paths_status)
    omitted = [path for path in paths if is_process_artifact(path)]
    omitted_set = set(omitted)
    rendered = {
        path: (
            OMISSION_MARKER.format(path=path).encode()
            if path in omitted_set
            else file_diff(repo, base, path, unified_for(path, variant))
        )
        for path in paths
    }
    # An omitted file's marker counts toward its share like any other content:
    # it is trivially small, so it never meaningfully taxes the pool.
    shares = allocate({p: len(c) for p, c in rendered.items()}, variant.total_cap)

    chunks: list[bytes] = []
    truncated: list[str] = []
    for path in paths:
        if not rendered[path]:
            chunks.append(UNAVAILABLE_MARKER.format(path=path).encode())
            truncated.append(path)
            continue
        body, boundary = fit(rendered[path], shares[path], path)
        if boundary is not None:
            truncated.append(path)
        chunks.append(body)
    blob = b"".join(chunks)
    # Both files land only once every diff is assembled, so a git failure
    # part-way leaves no half-written context for a reviewer to be handed.
    (directory / "changed-files.txt").write_bytes(status)
    (directory / "pr.diff").write_bytes(blob)

    return VariantResult(
        variant=variant,
        directory=directory,
        total=len(blob),
        file_count=len(paths),
        truncated=truncated,
        omitted=omitted,
    )


def report(results: list[VariantResult]) -> str:
    """The summary `/pr-review` reads: paths, budgets, and truncation state."""
    lines = []
    for res in results:
        lines.append(
            f"{res.variant.name}: {res.file_count} files, "
            f"{res.total}/{res.variant.total_cap} B, "
            f"{len(res.truncated)} truncated, {len(res.omitted)} omitted"
        )
        lines.append(f"  changed-files: {res.directory / 'changed-files.txt'}")
        lines.append(f"  diff:          {res.directory / 'pr.diff'}")
        for path in res.truncated:
            lines.append(f"  TRUNCATED: {path}")
        for path in res.omitted:
            lines.append(f"  omitted:   {path}")
    any_truncated = any(res.truncated for res in results)
    lines.append(f"TRUNCATION: {'yes' if any_truncated else 'none'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="directory to write the variants into (keep it outside the worktree)",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="the worktree to diff (default: the current directory)",
    )
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="branch the PR targets (default: origin/main)",
    )
    parser.add_argument(
        "--merge-base",
        help="use this SHA as the range start instead of computing the merge base",
    )
    args = parser.parse_args(argv)

    try:
        repo = worktree_root(args.repo.resolve())
    except (RuntimeError, OSError) as exc:
        print(f"Could not resolve the worktree root: {exc}", file=sys.stderr)
        return 1
    if repo == args.out_dir.resolve() or repo in args.out_dir.resolve().parents:
        parser.error(
            f"--out-dir {args.out_dir} is inside the worktree {repo}; "
            "write the context outside it so it never lands in a diff"
        )
    try:
        # Cleared before anything can fail, so no exit path leaves a previous
        # head's context on disk for a reviewer to be handed.
        for variant in VARIANTS:
            clear_variant_dir(args.out_dir / variant.name)
        base = args.merge_base or merge_base(repo, args.base_ref)
        status = name_status(repo, base)
        paths_status = name_status_z(repo, base)
        if not changed_paths(paths_status):
            print(f"No changed files against {base}.", file=sys.stderr)
            return 1

        results = [
            build_variant(repo, base, variant, args.out_dir, status, paths_status)
            for variant in VARIANTS
        ]
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Could not build the review context: {exc}", file=sys.stderr)
        return 1

    print(f"merge base: {base}")
    print(report(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
