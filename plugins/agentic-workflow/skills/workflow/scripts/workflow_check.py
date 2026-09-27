#!/usr/bin/env python3
"""Verify a project against the per-feature workflow layout.

The `workflow` skill's `check` mode (`skills/workflow/SKILL.md`, in the
`agentic-workflow` plugin) runs this instead of reading the layout by prompt:
every rule below is a fact about files that a skill downstream depends on,
and a prompt that re-derives them drifts.

What is checked, in order:

* the layout -- ``roadmap.md``, ``AGENTS.md``, ``CLAUDE.md``, ``docs/features/``,
  ``docs/deferred.md``, ``docs/weak-spots.md``, ``docs/retros/``;
* balanced code fences in every file parsed below, since an unclosed one
  hides every heading after it;
* the sections the skills read -- ``AGENTS.md`` → Domain rules for code
  review, Release model, Weak spots; ``CLAUDE.md`` → Commands, Models;
* the ``## Models`` table -- one row per tier, every floor and recommendation
  a model named on the order line, no recommendation below its floor;
* ``roadmap.md`` -- Direction, Features, Done, Backlog; every Features row
  carries a valid status; a row at ``planned`` or later links a folder that
  exists, no two rows link the same folder, and every folder has a row whose
  status agrees with the file. A signed-off feature moves to ``## Done``, and
  a folder linked from there counts as ``done``. The optional ``After``
  column of ``## Features`` lists, comma-separated, the features a row cannot
  start before: every entry names a row in ``## Features`` or ``## Done``,
  and the entries form no cycle;
* every ``docs/features/<slug>/feature.md`` -- frontmatter ``status`` (one a
  feature folder can hold: ``planned`` and later), ``depends-on``,
  ``dark-ship``, ``checkpoint``; a ``## Chunks`` section with
  ``### <n> — <name>`` headings; a ``## Test checkpoint`` section; a
  ``manual_tests.md`` beside it once the feature is ``building``;
* every ``depends-on`` entry names ``<feature>/<chunk>`` where both exist;
* every ``chunks/<n>-<slug>.md`` names a chunk ``feature.md`` has a heading
  for, and carries the ``Build model:`` line ``/build`` refuses to start
  without;
* every ``dark-ship`` line names a server-side enforcement point, as a
  backticked reference shaped like code (a path, a dotted or underscored
  identifier, a call) that is not a template, stylesheet or script -- free
  prose, backticked prose and UI-only references are rejected. This checks
  the shape of the claim, not that the gate it names holds;
* ``docs/weak-spots.md`` -- the five columns present, every row carrying all
  five, at most 30 rows.

A file that cannot be *read* is itself a finding rather than a traceback.
Directory traversal is not wrapped: an unreadable ``docs/features/`` still
raises, which is a broken checkout rather than a layout problem.

Exit status is 0 when nothing fails, 1 otherwise. Each finding is one line,
``<file>: <what>``, so the output can be quoted verbatim.

Usage::

    python skills/workflow/scripts/workflow_check.py [--root <repo>]
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

STATUSES = ("idea", "outlined", "planned", "building", "built", "done")
"""Feature status values, in order (``roadmap.md`` → "Status values")."""

FOLDER_STATUSES = STATUSES[2:]
"""Statuses at which ``docs/features/<slug>/`` must exist."""

TIERS = ("planning", "coding", "fix-review", "quality review", "security review")
"""The rows the ``## Models`` table must carry, one per skill tier."""

WEAK_SPOT_CAP = 30
WEAK_SPOT_COLUMNS = ("Class", "Tag", "What to check", "Added", "Last fired")

REQUIRED_PATHS = (
    "roadmap.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/features",
    "docs/deferred.md",
    "docs/weak-spots.md",
    "docs/retros",
)

AGENTS_SECTIONS = ("Domain rules for code review", "Release model", "Weak spots")
CLAUDE_SECTIONS = ("Commands", "Models")
ROADMAP_SECTIONS = ("Direction", "Features", "Done", "Backlog")
FEATURE_SECTIONS = ("Chunks", "Test checkpoint")
FRONTMATTER_KEYS = ("status", "depends-on", "dark-ship", "checkpoint")

UI_ONLY_PATTERNS = ("*.html", "*templates/*", "*.jinja", "*.jinja2", "*.css", "*.js")
"""A backticked reference matching one of these is UI concealment, not a gate."""
CODE_REFERENCE = re.compile(r"^\w+([./_]\w+)+$|^\w+\(\)$")
"""What a backticked reference must look like to count as an enforcement point.

A column, path, module or function carries a separator and no whitespace:
``accounts.feature_enabled``, ``shared/services/gate.py``, ``is_feature_enabled``.
Backticks around prose do not -- ``the page is `hidden` from the menu`` would
otherwise satisfy the check on the word ``hidden`` alone, which is the UI
concealment the rule exists to reject. Alphanumerics are required on both
sides of every separator, so an abbreviation like ``e.g.`` does not qualify
either."""
FEATURE_BRANCH = "feature branch"
"""The one accepted non-gate value: the feature cannot ship dark."""

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
CHUNK_HEADING = re.compile(r"^###\s+(\S+)\s+[—-]+\s+\S")
FEATURE_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*([^|]+?)\s*\|")
"""The first two cells of a ``## Features`` row: the name and the status.

Anchored on the first two cells only, and the status cell is matched as
"everything up to the next pipe" rather than one token, so a table with a
fourth column, or a status written ``building (paused)``, still yields rows.
Silently yielding none would disable every folder-to-row check below."""
ROW_LINK = re.compile(r"^\[([^\]]+)\]\(([^)]+)\)$")
DEPENDS_ENTRY = re.compile(r"^([A-Za-z0-9][\w.-]*)/(\S+)")
BACKTICKED = re.compile(r"`([^`]+)`")
AFTER_NONE = frozenset({"", "-", "—", "–"})
"""An ``After`` cell reading as "waits on nothing"."""
BUILD_MODEL = re.compile(r"^Build model:\s*\S", re.M)
"""The closing line ``/plan`` writes and ``/build`` refuses to start without."""


class MalformedFrontmatter(Exception):
    """A frontmatter block with one unparseable line.

    Distinct from "no frontmatter" so the finding names the offending line:
    reporting a one-character typo as a missing block, plus one finding per
    key it could not read, points the reader away from the actual edit.
    """

    def __init__(self, line: str) -> None:
        super().__init__(line)
        self.line = line


@dataclass
class Report:
    """Findings, one line each, in the order they were found.

    A finding is recorded once. Several checks legitimately read the same
    file -- ``CLAUDE.md`` is read by the fence, section and model checks --
    so without this an unreadable one would be reported three times and the
    summary would count three findings for a single cause.
    """

    findings: list[str] = field(default_factory=list)

    def fail(self, path: str, what: str) -> None:
        finding = f"{path}: {what}"
        if finding not in self.findings:
            self.findings.append(finding)

    @property
    def ok(self) -> bool:
        return not self.findings


def read_text(path: Path, rel: str, report: Report) -> str | None:
    """Read a file, turning one that cannot be read into a finding.

    Every check parses text, so letting a decode or IO error escape would
    abort the whole run with a traceback instead of the ``<file>: <what>``
    line this script promises -- and because the live repo is a pytest
    fixture, that surfaces as an opaque test error rather than something a
    reader can act on. ``None`` means "reported, skip this file".
    """
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as error:
        report.fail(rel, f"cannot be read ({type(error).__name__})")
        return None


def sections(text: str, level: int) -> dict[str, str]:
    """Map each heading at ``level`` (lower-cased) to the text under it."""
    found: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    open_marker: str | None = None
    for line in text.splitlines():
        marker = _fence_marker(line)
        if marker is not None:
            if open_marker is None:
                open_marker = marker
            elif marker == open_marker:
                open_marker = None
        match = None if open_marker is not None else HEADING.match(line)
        if match and len(match.group(1)) <= level:
            if current is not None:
                found[current] = "\n".join(body)
            current = match.group(2).lower() if len(match.group(1)) == level else None
            body = []
            continue
        body.append(line)
    if current is not None:
        found[current] = "\n".join(body)
    return found


def has_section(text: str, level: int, title: str) -> bool:
    return title.lower() in sections(text, level)


def _fence_marker(line: str) -> str | None:
    """The fence character run that opens or closes a block, if this is one."""
    stripped = line.lstrip()
    for marker in ("```", "~~~"):
        if stripped.startswith(marker):
            return marker
    return None


def fences_balanced(text: str) -> bool:
    """False if a code fence is opened and never closed.

    A fence closes only on its own marker, so a ``~~~`` block quoting a
    ``` example -- which these prompt files do -- is balanced, not an
    imbalance. Counting fence lines by parity reported those as broken, and
    since the live repo is a test fixture that would have failed the suite on
    an unrelated docs edit.

    :func:`sections` treats everything after an unclosed fence as fenced, so
    every heading past it disappears and the file quietly passes checks that
    should have run. A silent pass on a malformed file is the worst thing
    this script can do, so a real imbalance is a finding.
    """
    open_marker: str | None = None
    for line in text.splitlines():
        marker = _fence_marker(line)
        if marker is None:
            continue
        if open_marker is None:
            open_marker = marker
        elif marker == open_marker:
            open_marker = None
    return open_marker is None


def frontmatter(text: str) -> dict[str, str] | None:
    """Return the top-level keys of a YAML frontmatter block, or None.

    Only the shape the skills write is parsed: ``key: value`` lines and
    ``key:`` followed by ``- item`` lines (joined with newlines), with blank
    lines and ``#`` comments ignored. A block that does not open and close
    with ``---`` is "no frontmatter", and so is one holding a line that is
    none of those.

    Two failure shapes, because they have different fixes. A line carrying a
    colon but an unusable key (``dark ship: x``) is a typo in real
    frontmatter, and raises :class:`MalformedFrontmatter` naming it. A line
    with no colon at all means the block was never frontmatter, or never
    closed and this is body prose -- that is "no frontmatter", reported as
    ``None``, and must not be described as a broken key.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return None
    keys: dict[str, str] = {}
    current: str | None = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) or line.lstrip().startswith("- "):
            if current is not None:
                item = line.strip()
                item = item[2:] if item.startswith("- ") else item
                keys[current] = f"{keys[current]}\n{item}".strip()
            continue
        key, sep, value = line.partition(":")
        if not sep:
            return None
        if not key.strip() or " " in key.strip():
            raise MalformedFrontmatter(line.strip())
        current = key.strip()
        keys[current] = value.strip()
    return keys


def list_items(value: str) -> list[str]:
    """Split a frontmatter list value into its entries (``[]`` is empty)."""
    stripped = value.strip()
    if stripped in ("", "[]"):
        return []
    if stripped.startswith("[") and stripped.endswith("]"):
        return [item.strip().strip("'\"") for item in stripped[1:-1].split(",")]
    return [line.strip().strip("'\"") for line in stripped.splitlines() if line.strip()]


def chunk_numbers(feature_text: str) -> list[str]:
    """The ``<n>`` of every ``### <n> — <name>`` heading under ``## Chunks``."""
    chunks = sections(feature_text, 2).get("chunks", "")
    numbers = []
    for line in chunks.splitlines():
        match = CHUNK_HEADING.match(line)
        if match:
            numbers.append(match.group(1))
    return numbers


def dark_ship_ok(value: str) -> bool:
    """True if a dark-ship line names something enforceable outside the UI.

    The line must carry at least one backticked reference that both looks
    like code (:data:`CODE_REFERENCE`) and is not a template, stylesheet or
    script path -- a column, a function, a service module. Free prose is
    rejected outright, however server-side it sounds: "the page is not linked
    anywhere" reads like a gate and is exactly the UI concealment
    ``AGENTS.md`` -> Release model forbids, and no wording test can tell the
    two apart. Backticks alone do not make prose a reference, which is why
    the shape test is on the reference and not merely on its presence.
    ``feature branch`` is the one accepted non-gate value, for a feature that
    genuinely cannot ship dark.

    This is a shape check on the *claim*, not on the code: it cannot confirm
    the named gate exists, is reached on every path, or defaults off. A
    passing line is a reviewable claim, not a verified control.
    """
    text = value.strip().strip("'\"")
    if not text:
        return False
    if text.lower() == FEATURE_BRANCH:
        return True
    return any(
        CODE_REFERENCE.match(ref)
        and not any(fnmatch.fnmatch(ref, pattern) for pattern in UI_ONLY_PATTERNS)
        for ref in BACKTICKED.findall(text)
    )


def check_layout(root: Path, report: Report) -> None:
    for rel in REQUIRED_PATHS:
        if not (root / rel).exists():
            report.fail(rel, "missing")


def check_fences(root: Path, report: Report) -> None:
    """Every markdown file the other checks parse must close its fences."""
    paths = ["roadmap.md", "AGENTS.md", "CLAUDE.md", "docs/weak-spots.md"]
    features = root / "docs" / "features"
    if features.is_dir():
        paths += [
            f"docs/features/{folder.name}/feature.md"
            for folder in sorted(features.iterdir())
            if folder.is_dir() and (folder / "feature.md").exists()
        ]
    for rel in paths:
        path = root / rel
        if not path.exists():
            continue
        text = read_text(path, rel, report)
        if text is not None and not fences_balanced(text):
            report.fail(rel, "a code fence is opened and never closed")


def check_sections(root: Path, report: Report) -> None:
    for rel, required in (
        ("AGENTS.md", AGENTS_SECTIONS),
        ("CLAUDE.md", CLAUDE_SECTIONS),
    ):
        path = root / rel
        if not path.exists():
            continue
        text = read_text(path, rel, report)
        if text is None:
            continue
        for title in required:
            if not has_section(text, 2, title):
                report.fail(rel, f"missing section `## {title}`")


def check_models(root: Path, report: Report) -> None:
    path = root / "CLAUDE.md"
    if not path.exists():
        return
    text = read_text(path, "CLAUDE.md", report)
    if text is None:
        return
    models = sections(text, 2).get("models")
    if models is None:
        return
    order_match = re.search(r"weakest first:\s*([^(\n]+)", models)
    if not order_match:
        report.fail("CLAUDE.md", "`## Models` has no `weakest first:` order line")
        return
    order = [m.strip() for m in re.split(r"\s*<\s*", order_match.group(1)) if m.strip()]
    rows = {}
    for line in models.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].lower() in TIERS:
            rows[cells[0].lower()] = (cells[1].lower(), cells[2].lower())
    for tier in TIERS:
        if tier not in rows:
            report.fail("CLAUDE.md", f"`## Models` table has no `{tier}` row")
            continue
        floor, recommended = rows[tier]
        for label, model in (("floor", floor), ("recommended", recommended)):
            if model not in order:
                report.fail(
                    "CLAUDE.md",
                    f"`{tier}` {label} `{model}` is not on the order line",
                )
        if floor in order and recommended in order:
            if order.index(recommended) < order.index(floor):
                report.fail(
                    "CLAUDE.md", f"`{tier}` recommends `{recommended}` below its floor"
                )


def roadmap_rows(text: str) -> list[tuple[str, str | None, str]]:
    """``(name, linked path or None, status)`` for each ``## Features`` row."""
    features = sections(text, 2).get("features", "")
    rows = []
    for line in features.splitlines():
        match = FEATURE_ROW.match(line.strip())
        if not match:
            continue
        name, status = match.groups()
        if name.lower() == "feature" or set(name) <= {"-", ":", " "}:
            continue
        link = ROW_LINK.match(name)
        if link:
            rows.append((link.group(1), link.group(2), status))
        else:
            rows.append((name.strip("`"), None, status))
    return rows


def slug_of(link: str) -> str:
    """The feature slug a row's link points at -- its folder name.

    Keyed on the path, never the link text: a row may legitimately read
    ``[Billing API](docs/features/w8-billing-api/feature.md)``, and matching
    on ``Billing API`` would report the folder as unlisted. A row may also
    link the folder itself rather than its ``feature.md``, so a link not
    ending in ``.md`` is already the slug.

    The test is for ``.md`` specifically, not for "has a suffix": a folder
    named ``v1.2-alpha`` looks suffixed (``.2-alpha``) and would otherwise
    resolve to its parent, leaving the real folder reported as unlisted.
    """
    path = PurePosixPath(link)
    return path.parent.name if path.suffix.lower() == ".md" else path.name


def done_links(text: str) -> list[str]:
    """Every folder linked from ``## Done``.

    A signed-off feature moves out of ``## Features`` into ``## Done`` -- that
    is where the lifecycle ends, and the row keeps its link when the feature
    has a folder. Without this a ``done`` feature would be reported as having
    no row the moment the human signs it off, which is the one transition the
    check must not punish.
    """
    done = sections(text, 2).get("done", "")
    return [
        match.group(2)
        for line in done.splitlines()
        for cell in [line.strip().strip("|").split("|")[0].strip()]
        if (match := ROW_LINK.match(cell))
    ]


def table(text: str) -> list[dict[str, str]]:
    """Body rows of the first Markdown table in ``text``, keyed by lower-cased
    header cell, so a column is found by its name rather than its position."""
    lines: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if lines:
                break
            continue
        lines.append([cell.strip() for cell in stripped.strip("|").split("|")])
    if not lines:
        return []
    header = [cell.lower() for cell in lines[0]]
    return [
        dict(zip(header, row))
        for row in lines[1:]
        if not all(set(cell) <= set("-: ") for cell in row)
    ]


def row_slug(cell: str) -> str:
    """The slug a table row names: its folder when linked, else its name."""
    link = ROW_LINK.match(cell)
    return slug_of(link.group(2)) if link else cell.strip("`")


def after_entries(cell: str) -> list[str]:
    """The features an ``After`` cell names, comma-separated; a dash is none."""
    entries = (entry.strip().strip("`").strip() for entry in cell.split(","))
    return [entry for entry in entries if entry not in AFTER_NONE]


def _cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """One cycle in ``graph`` as ``[a, b, ..., a]``, or None."""
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        path.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                return path[path.index(nxt) :] + [nxt]
            if nxt not in state and (found := visit(nxt)):
                return found
        path.pop()
        state[node] = 2
        return None

    for node in graph:
        if node not in state and (found := visit(node)):
            return found
    return None


def check_after(text: str, report: Report) -> None:
    """Every ``After`` entry names a roadmap row, and together they form no
    cycle. A table without the column declares nothing, so passes as is."""
    parts = sections(text, 2)
    rows = table(parts.get("features", ""))
    known = {
        row_slug(next(iter(row.values()), ""))
        for part in ("features", "done")
        for row in table(parts.get(part, ""))
    }
    graph: dict[str, list[str]] = {}
    for row in rows:
        slug = row_slug(next(iter(row.values()), ""))
        entries = after_entries(row.get("after", ""))
        for entry in entries:
            if entry not in known:
                report.fail(
                    "roadmap.md", f"`{slug}` is after `{entry}`, which has no row"
                )
        graph[slug] = [entry for entry in entries if entry in known]
    cycle = _cycle(graph)
    if cycle:
        loop = " → ".join(f"`{slug}`" for slug in cycle)
        report.fail("roadmap.md", f"`After` entries form a cycle: {loop}")


def check_roadmap(root: Path, report: Report) -> dict[str, str]:
    """Check ``roadmap.md`` and return ``{folder slug: status}`` for linked rows."""
    path = root / "roadmap.md"
    if not path.exists():
        return {}
    text = read_text(path, "roadmap.md", report)
    if text is None:
        return {}
    for title in ROADMAP_SECTIONS:
        if not has_section(text, 2, title):
            report.fail("roadmap.md", f"missing section `## {title}`")
    check_after(text, report)
    statuses: dict[str, str] = {}
    for name, link, status in roadmap_rows(text):
        if status not in STATUSES:
            report.fail("roadmap.md", f"`{name}` has unknown status `{status}`")
            continue
        if status in FOLDER_STATUSES:
            if link is None:
                report.fail("roadmap.md", f"`{name}` is `{status}` but links no folder")
            elif not (root / link).exists():
                report.fail("roadmap.md", f"`{name}` links `{link}`, which is missing")
            else:
                slug = slug_of(link)
                if slug in statuses:
                    report.fail("roadmap.md", f"two rows link `{slug}`")
                statuses[slug] = status
        elif link is not None:
            report.fail("roadmap.md", f"`{name}` is `{status}` but links a folder")
    for link in done_links(text):
        if (root / link).exists():
            statuses.setdefault(slug_of(link), "done")
    return statuses


def check_features(root: Path, report: Report, index: dict[str, str]) -> None:
    features_dir = root / "docs" / "features"
    if not features_dir.is_dir():
        return
    folders = sorted(p for p in features_dir.iterdir() if p.is_dir())
    texts: dict[str, str] = {}
    unreadable: set[str] = set()
    for folder in folders:
        rel = f"docs/features/{folder.name}/feature.md"
        path = folder / "feature.md"
        if not path.exists():
            report.fail(rel, "missing")
            continue
        text = read_text(path, rel, report)
        if text is None:
            unreadable.add(folder.name)
        else:
            texts[folder.name] = text
    for slug, text in texts.items():
        rel = f"docs/features/{slug}/feature.md"
        # A frontmatter problem is reported once and then set aside: the body
        # and the chunk files are checked regardless. Bailing out here instead
        # would hide every other finding for this feature behind one typo, so
        # fixing the typo would surface a second wave on the next run -- the
        # silent skip this script's own docstring calls its worst failure.
        # Every key-dependent check below already degrades safely on ``{}``.
        readable = True
        try:
            meta = frontmatter(text)
        except MalformedFrontmatter as bad:
            report.fail(rel, f"frontmatter line is not `key: value`: `{bad.line}`")
            meta, readable = {}, False
        if meta is None:
            report.fail(rel, "no frontmatter block")
            meta = {}
        if readable:
            for key in FRONTMATTER_KEYS:
                if key not in meta:
                    report.fail(rel, f"frontmatter lacks `{key}`")
        status = meta.get("status", "")
        if "status" in meta and status not in FOLDER_STATUSES:
            report.fail(rel, f"status `{status}` is not one a feature folder can hold")
        if slug not in index:
            report.fail(
                "roadmap.md", f"no row in `## Features` or `## Done` links `{rel}`"
            )
        elif "status" in meta and index[slug] != status:
            report.fail(
                rel, f"status `{status}` disagrees with roadmap.md `{index[slug]}`"
            )
        for title in FEATURE_SECTIONS:
            if not has_section(text, 2, title):
                report.fail(rel, f"missing section `## {title}`")
        if has_section(text, 2, "Chunks") and not chunk_numbers(text):
            report.fail(rel, "`## Chunks` has no `### <n> — <name>` heading")
        if (
            status in FOLDER_STATUSES[1:]
            and not (root / rel).with_name("manual_tests.md").exists()
        ):
            report.fail(
                f"docs/features/{slug}/manual_tests.md", f"missing while `{status}`"
            )
        if "dark-ship" in meta and not dark_ship_ok(meta["dark-ship"]):
            report.fail(rel, "`dark-ship` names no server-side enforcement point")
        check_chunks(report, text, features_dir / slug)
        for entry in list_items(meta.get("depends-on", "")):
            match = DEPENDS_ENTRY.match(entry)
            if not match:
                report.fail(rel, f"depends-on `{entry}` is not `<feature>/<chunk>`")
                continue
            dep_slug, dep_chunk = match.groups()
            if dep_slug in unreadable:
                # The folder is there; its feature.md just could not be read,
                # and that is already reported against the file itself. Saying
                # "no folder" here would send the reader to the wrong place.
                report.fail(
                    rel, f"depends-on `{entry}` names a feature that could not be read"
                )
            elif dep_slug not in texts:
                report.fail(rel, f"depends-on `{entry}` names a feature with no folder")
            elif dep_chunk not in chunk_numbers(texts[dep_slug]):
                report.fail(
                    rel, f"depends-on `{entry}` names a chunk that does not exist"
                )


def check_chunks(report: Report, feature_text: str, folder: Path) -> None:
    """Every chunk file names a real chunk and carries the line ``/build`` needs.

    ``/build`` hard-gates on a ``Build model:`` line and finds its file by the
    chunk number, so a mis-slugged file makes it stop with "run /plan first"
    while a perfectly good plan sits beside it.
    """
    chunks_dir = folder / "chunks"
    if not chunks_dir.is_dir():
        return
    numbers = set(chunk_numbers(feature_text))
    for path in sorted(chunks_dir.glob("*.md")):
        rel = f"docs/features/{folder.name}/chunks/{path.name}"
        number = path.stem.split("-", 1)[0]
        if number not in numbers:
            report.fail(
                rel, f"names chunk `{number}`, which feature.md has no heading for"
            )
        chunk_text = read_text(path, rel, report)
        if chunk_text is not None and not BUILD_MODEL.search(chunk_text):
            report.fail(rel, "has no `Build model:` line")


def check_weak_spots(root: Path, report: Report) -> None:
    path = root / "docs" / "weak-spots.md"
    if not path.exists():
        return
    text = read_text(path, "docs/weak-spots.md", report)
    if text is None:
        return
    rows = []
    header_ok = False
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if tuple(cells) == WEAK_SPOT_COLUMNS:
            header_ok = True
        elif header_ok and not set(cells[0]) <= {"-", ":", " "}:
            rows.append(cells)
    if not header_ok:
        report.fail(
            "docs/weak-spots.md",
            "table columns are not " + " | ".join(WEAK_SPOT_COLUMNS),
        )
    for number, cells in enumerate(rows, start=1):
        if len(cells) != len(WEAK_SPOT_COLUMNS):
            report.fail(
                "docs/weak-spots.md",
                f"row {number} has {len(cells)} cells, "
                f"expected {len(WEAK_SPOT_COLUMNS)}",
            )
    if len(rows) > WEAK_SPOT_CAP:
        report.fail(
            "docs/weak-spots.md", f"{len(rows)} entries, cap is {WEAK_SPOT_CAP}"
        )


def run(root: Path) -> Report:
    report = Report()
    check_layout(root, report)
    check_fences(root, report)
    check_sections(root, report)
    check_models(root, report)
    index = check_roadmap(root, report)
    check_features(root, report, index)
    check_weak_spots(root, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root")
    args = parser.parse_args(argv)
    report = run(args.root.resolve())
    for line in report.findings:
        print(line)
    print(
        f"workflow check: {'OK' if report.ok else f'{len(report.findings)} finding(s)'}"
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
