#!/usr/bin/env python3
"""Render a project's roadmap progress as one self-contained HTML page.

The ``progress`` skill (``skills/progress/SKILL.md``) runs this so the page
looks the same on every run and no part of the layout is re-derived by
prompt. It reads the files the other skills keep current and writes one HTML
file; it never edits the project.

What it reads:

* ``roadmap.md`` -- the H1 for the project name, then the ``## Done`` rows and
  the ``## Features`` rows, each in table order. That order is the roadmap's
  own sequence, so the page keeps it.
* ``docs/features/<slug>/feature.md`` for every row that links a folder: the
  frontmatter ``status`` (shown when it disagrees with the roadmap row) and
  ``depends-on``, the task boxes under each chunk heading, and the sign-off
  line under ``## Test checkpoint``.
* ``docs/features/<slug>/manual_tests.md``: the top-level ``- [ ]`` and
  ``- [x]`` items under each ``##`` checkpoint heading, and its sign-off line.

A dependency is met when its feature is ``built`` or ``done``, or, for a
``<feature>/<chunk>`` entry, when every task box under that chunk's heading is
ticked. A bare ``<feature>`` entry waits for the whole feature. Only features
with a folder carry ``depends-on``, so an ``outlined`` feature has no edges.

The table, section and frontmatter parsers are the ``workflow`` skill's own,
loaded from ``workflow_check.py`` by path, so anything the layout check
accepts is read the same way here.

The headline, summary and per-feature notes come from the caller. Everything
printed from the repository or the arguments is HTML-escaped.

Exit status is 0 when the page was written and 2 on a usage error: no
``roadmap.md``, or a ``--target`` or ``--note`` naming a feature the page does
not show.

Usage::

    python skills/progress/scripts/progress.py --out PATH [--root REPO]
        [--headline TEXT] [--summary TEXT] [--note SLUG=TEXT ...]
        [--target SLUG] [--date YYYY-MM-DD] [--fragment]
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

CHECK_SCRIPT = (
    Path(__file__).resolve().parents[2] / "workflow" / "scripts" / "workflow_check.py"
)


def _load_workflow_check():
    spec = importlib.util.spec_from_file_location("_progress_wc", CHECK_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


wc = _load_workflow_check()

IN_FLIGHT = ("planned", "building", "built")
MET_STATUSES = ("built", "done")
PROJECT_H1 = re.compile(r"^#\s+(?:Roadmap\s*[—–-]+\s*)?(.+?)\s*$", re.M)
CHECKPOINT_HEADING = re.compile(r"^##\s+(.+?)\s*$")
TOP_LEVEL_BOX = re.compile(r"^- \[([ xX])\]")
ANY_BOX = re.compile(r"^\s*- \[([ xX])\]", re.M)
SIGN_OFF = re.compile(r"Signed off by:\s*(.+)", re.I)
CODE_SPAN = re.compile(r"`([^`]+)`")
MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
BOLD = re.compile(r"\*\*([^*]+)\*\*")


class UsageError(Exception):
    """A bad argument or a missing input; reported as one line, exit 2."""


@dataclass
class Checkpoint:
    name: str
    ticked: int = 0
    total: int = 0


@dataclass
class Dependency:
    entry: str
    slug: str
    chunk: str | None
    met: bool = False
    upstream: int | None = None
    """The upstream feature's index on the page, or None if it is not shown."""


@dataclass
class Feature:
    slug: str
    name: str
    status: str
    line: str
    link: str | None = None
    shipped: str | None = None
    folder_status: str | None = None
    checkpoints: list[Checkpoint] = field(default_factory=list)
    signed_off: str | None = None
    depends: list[Dependency] = field(default_factory=list)
    note: str | None = None
    text: str | None = None

    @property
    def kind(self) -> str:
        """The status as one of ``STATUSES``; a cell like ``building (paused)``
        styles as ``building``, and anything unrecognised as ``idea``."""
        words = self.status.split()
        word = words[0].lower() if words else ""
        return word if word in wc.STATUSES else "idea"


@dataclass
class Page:
    project: str
    features: list[Feature]
    target: str | None = None


def table_rows(text: str) -> list[list[str]]:
    """Body rows of the first Markdown table in ``text``, as stripped cells."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        rows.append([cell.strip() for cell in stripped.strip("|").split("|")])
    return [row for row in rows[1:] if not all(set(cell) <= set("-: ") for cell in row)]


def _row(cells: list[str], status: str | None) -> Feature | None:
    if not cells or not cells[0]:
        return None
    link_match = wc.ROW_LINK.match(cells[0])
    if link_match:
        name, link = link_match.group(1), link_match.group(2)
        slug = wc.slug_of(link)
    else:
        name, link = cells[0].strip("`"), None
        slug = name
    second = cells[1] if len(cells) > 1 else ""
    return Feature(
        slug=slug,
        name=name,
        status=status if status is not None else second,
        shipped=second if status is not None else None,
        line=cells[2] if len(cells) > 2 else "",
        link=link,
    )


def sign_off(text: str) -> str | None:
    """Who signed a checkpoint off, from a ``Signed off by: <who>`` line.

    The line may wrap (``Signed off`` / ``by: ...``), so each paragraph is
    flattened first. The template's ``<human, date>`` placeholder is not a
    sign-off.
    """
    for paragraph in re.split(r"\n\s*\n", text):
        match = SIGN_OFF.search(" ".join(paragraph.split()))
        if match:
            value = match.group(1).strip().rstrip(".").strip()
            if value and not value.startswith("<"):
                return value
    return None


def checkpoints(text: str) -> list[Checkpoint]:
    """Ticked and total top-level items under each ``##`` heading.

    Only unindented items count: a manual test is one ``- [ ]`` line with its
    steps nested beneath it. Boxes inside a code fence are examples, not items.
    """
    found: list[Checkpoint] = []
    current: Checkpoint | None = None
    fence: str | None = None
    for line in text.splitlines():
        marker = wc._fence_marker(line)
        if marker is not None:
            fence = marker if fence is None else (None if marker == fence else fence)
            continue
        if fence is not None:
            continue
        heading = CHECKPOINT_HEADING.match(line)
        if heading:
            current = Checkpoint(heading.group(1))
            found.append(current)
            continue
        box = TOP_LEVEL_BOX.match(line)
        if box:
            if current is None:
                current = Checkpoint("Checkpoint")
                found.append(current)
            current.total += 1
            current.ticked += box.group(1) in "xX"
    return [checkpoint for checkpoint in found if checkpoint.total]


def dependencies(value: str) -> list[Dependency]:
    """``depends-on`` entries: ``<feature>/<chunk>`` or a bare ``<feature>``."""
    found = []
    for entry in wc.list_items(value):
        token = entry.split()[0] if entry.split() else ""
        if not token:
            continue
        match = wc.DEPENDS_ENTRY.match(token)
        if match:
            found.append(Dependency(token, match.group(1), match.group(2)))
        else:
            found.append(Dependency(token, token, None))
    return found


def chunk_ticked(feature_text: str, number: str) -> bool:
    """True when chunk ``number`` has task boxes and every one is ticked."""
    body: list[str] = []
    inside = False
    for line in wc.sections(feature_text, 2).get("chunks", "").splitlines():
        heading = wc.CHUNK_HEADING.match(line)
        if heading:
            inside = heading.group(1) == number
            continue
        if inside:
            body.append(line)
    boxes = ANY_BOX.findall("\n".join(body))
    return bool(boxes) and all(box in "xX" for box in boxes)


def _read_folder(root: Path, feature: Feature) -> None:
    if feature.link is None:
        return
    folder = root / feature.link
    if folder.suffix.lower() == ".md":
        folder = folder.parent
    feature_md = folder / "feature.md"
    if feature_md.is_file():
        text = feature_md.read_text(encoding="utf-8")
        feature.text = text
        try:
            meta = wc.frontmatter(text) or {}
        except wc.MalformedFrontmatter:
            meta = {}
        feature.folder_status = meta.get("status") or None
        feature.depends = dependencies(meta.get("depends-on", ""))
        test_section = wc.sections(text, 2).get("test checkpoint", "")
        feature.signed_off = sign_off(test_section)
    manual = folder / "manual_tests.md"
    if manual.is_file():
        manual_text = manual.read_text(encoding="utf-8")
        feature.checkpoints = checkpoints(manual_text)
        feature.signed_off = feature.signed_off or sign_off(manual_text)


def _resolve(features: list[Feature]) -> None:
    index = {feature.slug: position for position, feature in enumerate(features)}
    for feature in features:
        for dep in feature.depends:
            position = index.get(dep.slug)
            if position is None:
                continue
            upstream = features[position]
            dep.upstream = position
            dep.met = upstream.kind in MET_STATUSES or bool(
                dep.chunk and upstream.text and chunk_ticked(upstream.text, dep.chunk)
            )


def build(
    root: Path, target: str | None = None, notes: dict[str, str] | None = None
) -> Page:
    """Read the project at ``root`` into a :class:`Page`."""
    path = root / "roadmap.md"
    if not path.is_file():
        raise UsageError(f"{path}: not found; run this from a project's root")
    text = path.read_text(encoding="utf-8")
    heading = PROJECT_H1.search(text)
    project = heading.group(1) if heading else root.resolve().name
    parts = wc.sections(text, 2)
    features = [
        feature
        for cells in table_rows(parts.get("done", ""))
        if (feature := _row(cells, "done"))
    ] + [
        feature
        for cells in table_rows(parts.get("features", ""))
        if (feature := _row(cells, None))
    ]
    for feature in features:
        _read_folder(root, feature)
    _resolve(features)

    page = Page(project, features)
    if target is not None:
        slugs = [feature.slug for feature in features]
        if target not in slugs:
            raise UsageError(f"--target `{target}` is not a feature on the roadmap")
        page.features = features[: slugs.index(target) + 1]
        page.target = target
        for feature in page.features:
            for dep in feature.depends:
                if dep.upstream is not None and dep.upstream >= len(page.features):
                    dep.upstream = None
    shown = {feature.slug: feature for feature in page.features}
    for slug, note in (notes or {}).items():
        if slug not in shown:
            raise UsageError(f"--note `{slug}` is not a feature on this page")
        shown[slug].note = note
    return page


def inline(text: str) -> str:
    """Escape ``text`` and keep the three Markdown marks the roadmap uses."""
    out = html.escape(MD_LINK.sub(r"\1", text))
    out = CODE_SPAN.sub(r"<code>\1</code>", out)
    return BOLD.sub(r"<b>\1</b>", out)


def _pill(feature: Feature, is_target: bool) -> str:
    if is_target:
        return '<span class="pill target">Target</span>'
    kind = feature.kind
    css = "done" if kind == "done" else "flight" if kind in IN_FLIGHT else "later"
    label = "Done" if kind == "done" else feature.status or kind
    return f'<span class="pill {css}">{html.escape(label)}</span>'


def _node(feature: Feature, position: int, is_target: bool) -> str:
    if is_target:
        return "&#9873;"
    if feature.kind == "done":
        return "&#10003;"
    if feature.kind in IN_FLIGHT:
        return "&#9679;"
    return str(position + 1)


def _checkpoint_html(feature: Feature) -> str:
    if not feature.checkpoints:
        return ""
    ticked = sum(c.ticked for c in feature.checkpoints)
    total = sum(c.total for c in feature.checkpoints)
    signed = feature.signed_off
    if feature.kind == "done" or (signed and ticked == total):
        who = f" &middot; signed off by {html.escape(signed)}" if signed else ""
        return f'<p class="meta">Checkpoint {ticked}/{total} ticked{who}</p>'
    rows = []
    for checkpoint in feature.checkpoints:
        share = 100 * checkpoint.ticked / checkpoint.total
        rows.append(
            '<div class="cp-row">'
            f'<span class="cp-name">{inline(checkpoint.name)}</span>'
            f'<span class="cp-bar"><i style="width:{share:.1f}%"></i></span>'
            f'<span class="cp-count">{checkpoint.ticked}/{checkpoint.total}</span>'
            "</div>"
        )
    state = (
        f"Signed off by {html.escape(signed)}"
        if signed
        else "Checkpoint not signed off yet"
    )
    return (
        '<div class="checkpoints">'
        '<p class="cp-title">Manual checkpoint</p>'
        + "".join(rows)
        + f'<p class="meta">{state}</p></div>'
    )


def _deps_html(feature: Feature) -> str:
    if not feature.depends:
        return ""
    chips = []
    for dep in feature.depends:
        label = html.escape(dep.entry)
        if dep.met:
            chips.append(f'<span class="chip met">{label} &#10003;</span>')
        elif dep.upstream is None:
            chips.append(f'<span class="chip wait">{label} &middot; not shown</span>')
        else:
            chips.append(f'<span class="chip wait">{label} &middot; waiting</span>')
    return (
        '<div class="deps"><span class="deps-label">Depends on</span>'
        + "".join(chips)
        + "</div>"
    )


def _stage(feature: Feature, position: int, focus: set[int], target: bool) -> str:
    classes = ["stage", f"k-{feature.kind}"]
    if position in focus:
        classes.append("focus")
    if target:
        classes.append("target")
    mismatch = ""
    if feature.folder_status and feature.folder_status != feature.kind:
        mismatch = (
            '<span class="chip warn">feature.md says '
            f"<code>{html.escape(feature.folder_status)}</code></span>"
        )
    shipped = (
        f'<p class="meta">Shipped {html.escape(feature.shipped)}</p>'
        if feature.shipped
        else ""
    )
    note = f'<p class="note">{inline(feature.note)}</p>' if feature.note else ""
    line = f'<p class="line">{inline(feature.line)}</p>' if feature.line else ""
    return (
        f'<div class="{" ".join(classes)}">'
        f'<div class="node" aria-hidden="true">{_node(feature, position, target)}</div>'
        '<div class="card"><div class="card-top">'
        f'<span class="name">{html.escape(feature.name)}</span>'
        f"{_pill(feature, target)}</div>"
        f"{line}{mismatch}{_deps_html(feature)}{_checkpoint_html(feature)}"
        f"{note}{shipped}</div></div>"
    )


def render(
    page: Page,
    *,
    headline: str | None = None,
    summary: str | None = None,
    generated: str = "",
    fragment: bool = False,
) -> str:
    """The page as HTML; a full document unless ``fragment`` is set."""
    features = page.features
    total = len(features)
    done = sum(feature.kind == "done" for feature in features)
    flight = [i for i, f in enumerate(features) if f.kind in IN_FLIGHT]
    upcoming = [i for i, f in enumerate(features) if f.kind != "done"]
    focus = set(flight or upcoming[:1])

    edges = [
        {"from": dep.upstream, "to": position, "met": dep.met}
        for position, feature in enumerate(features)
        for dep in feature.depends
        if dep.upstream is not None and dep.upstream != position
    ]
    gutter = 56 if edges else 0

    segments = "".join(
        '<span class="seg '
        + ("done" if f.kind == "done" else "flight" if f.kind in IN_FLIGHT else "later")
        + f'" title="{html.escape(f.name)}"></span>'
        for f in features
    )
    title = f"{page.project} Roadmap"
    lead = headline or f"{done} of {total} features done."
    dek = f'<p class="dek">{inline(summary)}</p>' if summary else ""
    legend = (
        '<p class="legend"><svg width="46" height="10" aria-hidden="true">'
        '<path class="arc met" d="M2 5 H20"/><path class="arc wait" d="M26 5 H44"/>'
        "</svg>Arcs join a feature to what it depends on: solid is met, "
        "dashed is still waiting.</p>"
        if edges
        else ""
    )
    stages = "".join(
        _stage(feature, i, focus, feature.slug == page.target)
        for i, feature in enumerate(features)
    )
    body = (
        f"<title>{html.escape(title)}</title>\n"
        f"{FONTS}\n<style>{CSS}</style>\n"
        '<main class="page">'
        f'<p class="eyebrow">{html.escape(page.project)} &middot; progress</p>'
        f"<h1>{inline(lead)}</h1>{dek}"
        '<section class="progress" aria-label="Overall progress">'
        '<div class="progress-head"><span class="label">Features</span>'
        f'<span class="count"><b>{done}</b> of {total} done'
        f" &middot; {len(flight)} in flight</span></div>"
        f'<div class="segments" style="--n:{max(total, 1)}">{segments}</div>'
        f"</section>{legend}"
        f'<div class="timeline" style="--gutter:{gutter}px">'
        f'<svg class="arcs" aria-hidden="true"></svg>{stages}</div>'
        "<footer><span>From roadmap.md and docs/features/</span>"
        f"<span>{html.escape(generated)}</span></footer></main>\n"
        '<script type="application/json" id="progress-edges">'
        f"{json.dumps(edges)}</script>\n"
        f"<script>{JS}</script>\n"
    )
    if fragment:
        return body
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"</head>\n<body>\n{body}</body>\n</html>\n"
    )


FONTS = (
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family='
    "IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700"
    '&display=swap">'
)

CSS = """
:root {
  --bg: #f1f3f1; --surface: #ffffff; --surface-muted: #e8ebe8;
  --border: #d7dcd8; --text: #1b211d; --text-muted: #5b655e;
  --accent: #b45f24; --accent-ink: #7a3f13; --accent-soft: #f1dcc7;
  --success: #2f7d5c; --success-soft: #d9ece2;
  --warn: #8a6d00; --warn-soft: #f5ecc4; --spine: #c3cac4;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14181a; --surface: #1b211d; --surface-muted: #232a25;
    --border: #303a33; --text: #eef1ee; --text-muted: #97a29a;
    --accent: #e2934f; --accent-ink: #f4b878; --accent-soft: #3a2c1c;
    --success: #59c393; --success-soft: #1c3327;
    --warn: #e6c65c; --warn-soft: #36301a; --spine: #3a443c;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #14181a; --surface: #1b211d; --surface-muted: #232a25;
  --border: #303a33; --text: #eef1ee; --text-muted: #97a29a;
  --accent: #e2934f; --accent-ink: #f4b878; --accent-soft: #3a2c1c;
  --success: #59c393; --success-soft: #1c3327;
  --warn: #e6c65c; --warn-soft: #36301a; --spine: #3a443c;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.5 'IBM Plex Sans', system-ui, -apple-system, sans-serif;
  padding: 40px 16px 64px;
}
.page { max-width: 760px; margin: 0 auto; }
code {
  font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .92em;
  background: var(--surface-muted); padding: 0 .3em; border-radius: 4px;
}
.eyebrow, .label, .cp-title, .deps-label, .pill, .meta, .count, .node,
.cp-count, footer {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
}
.eyebrow {
  margin: 0; font-size: 12px; font-weight: 600; letter-spacing: .12em;
  text-transform: uppercase; color: var(--accent-ink);
}
h1 {
  font-size: clamp(26px, 5vw, 36px); line-height: 1.12; margin: 8px 0 10px;
  letter-spacing: -.01em; text-wrap: balance;
}
.dek { color: var(--text-muted); font-size: 15px; max-width: 60ch; margin: 0 0 24px; }
.progress {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px 18px; margin: 8px 0 14px;
}
.progress-head {
  display: flex; justify-content: space-between; align-items: baseline;
  flex-wrap: wrap; gap: 8px; margin-bottom: 10px;
}
.label {
  font-size: 12px; letter-spacing: .06em; text-transform: uppercase;
  color: var(--text-muted);
}
.count {
  font-size: 13px; color: var(--text-muted); font-variant-numeric: tabular-nums;
}
.count b { color: var(--text); }
.segments { display: grid; grid-template-columns: repeat(var(--n), 1fr); gap: 4px; }
.seg {
  height: 7px; border-radius: 3px; background: var(--surface-muted);
  border: 1px solid var(--border);
}
.seg.done { background: var(--success); border-color: var(--success); }
.seg.flight { background: var(--accent); border-color: var(--accent); }
.legend {
  display: flex; align-items: center; gap: 8px; margin: 0 0 22px;
  font-size: 12px; color: var(--text-muted);
}
.timeline {
  position: relative; margin-top: 30px;
  padding-left: calc(var(--gutter, 0px) + 34px);
}
.arcs { position: absolute; left: 0; top: 0; overflow: visible; }
.arc { fill: none; stroke-width: 1.6; }
.arc.met { stroke: var(--success); }
.arc.wait { stroke: var(--accent); stroke-dasharray: 4 3; }
.arc-end.met { fill: var(--success); }
.arc-end.wait { fill: var(--accent); }
.stage { position: relative; padding-bottom: 26px; }
.stage::before {
  content: ""; position: absolute; left: -24px; top: 28px; bottom: -2px;
  width: 2px; background: var(--spine);
}
.stage.k-done::before { background: var(--success); }
.stage:last-child { padding-bottom: 0; }
.stage:last-child::before { display: none; }
.node {
  position: absolute; left: -34px; top: 4px; width: 22px; height: 22px;
  border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-size: 10px; color: var(--text-muted); background: var(--surface);
  border: 2px solid var(--spine);
}
.k-done .node {
  background: var(--success); border-color: var(--success);
  color: var(--success-soft);
}
.k-planned .node, .k-building .node, .k-built .node {
  background: var(--accent); border-color: var(--accent); color: var(--accent-soft);
}
.stage.target .node {
  background: var(--text); border-color: var(--text); color: var(--bg);
}
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px;
  display: flex; flex-direction: column; gap: 8px;
}
.stage.focus .card {
  border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent);
}
.card-top {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 8px;
}
.name { font-weight: 600; font-size: 15.5px; overflow-wrap: anywhere; }
.line { margin: 0; color: var(--text-muted); font-size: 13.5px; }
.pill {
  font-size: 10.5px; font-weight: 600; letter-spacing: .06em;
  text-transform: uppercase; padding: 3px 8px; border-radius: 999px;
  white-space: nowrap;
}
.pill.done { background: var(--success-soft); color: var(--success); }
.pill.flight { background: var(--accent-soft); color: var(--accent-ink); }
.pill.later {
  background: var(--surface-muted); color: var(--text-muted);
  border: 1px solid var(--border);
}
.pill.target { background: var(--text); color: var(--bg); }
.meta { margin: 0; font-size: 11px; color: var(--text-muted); }
.deps { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.deps-label { font-size: 11px; color: var(--text-muted); }
.chip {
  font-size: 12px; padding: 2px 8px; border-radius: 6px;
  border: 1px solid var(--border); overflow-wrap: anywhere;
}
.chip.met {
  color: var(--success); background: var(--success-soft);
  border-color: transparent;
}
.chip.wait {
  color: var(--accent-ink); background: var(--accent-soft);
  border-color: transparent;
}
.chip.warn {
  align-self: flex-start; color: var(--warn); background: var(--warn-soft);
  border-color: transparent;
}
.chip.warn code { background: transparent; padding: 0; }
.checkpoints { display: flex; flex-direction: column; gap: 6px; }
.cp-title {
  margin: 0; font-size: 11px; letter-spacing: .06em; text-transform: uppercase;
  color: var(--text-muted);
}
.cp-row {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(60px, 34%) 48px;
  align-items: center; gap: 10px;
}
.cp-name { font-size: 12.5px; overflow-wrap: anywhere; }
.cp-bar {
  height: 8px; border-radius: 4px; background: var(--surface-muted);
  border: 1px solid var(--border); overflow: hidden;
}
.cp-bar i { display: block; height: 100%; background: var(--success); }
.cp-count { font-size: 11.5px; text-align: right; font-variant-numeric: tabular-nums; }
.note {
  margin: 0; padding: 10px 12px; border-radius: 8px;
  background: var(--accent-soft); font-size: 13px;
}
footer {
  margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--border);
  display: flex; justify-content: space-between; flex-wrap: wrap; gap: 6px;
  font-size: 11.5px; color: var(--text-muted);
}
"""

JS = """
(function () {
  var data = document.getElementById("progress-edges");
  var timeline = document.querySelector(".timeline");
  var svg = timeline && timeline.querySelector(".arcs");
  if (!data || !svg) return;
  var edges = JSON.parse(data.textContent);
  if (!edges.length) return;
  var NS = "http://www.w3.org/2000/svg";
  function add(tag, attrs) {
    var el = document.createElementNS(NS, tag);
    for (var k in attrs) el.setAttribute(k, attrs[k]);
    svg.appendChild(el);
  }
  function draw() {
    var gutter = parseFloat(getComputedStyle(timeline).getPropertyValue("--gutter"));
    var stages = timeline.querySelectorAll(".stage");
    var height = timeline.offsetHeight;
    svg.setAttribute("width", gutter);
    svg.setAttribute("height", height);
    while (svg.lastChild) svg.removeChild(svg.lastChild);
    var x = gutter - 3;
    edges.forEach(function (e) {
      var a = stages[e.from], b = stages[e.to];
      if (!a || !b) return;
      var y1 = a.offsetTop + 15, y2 = b.offsetTop + 15;
      var span = Math.abs(e.to - e.from);
      var bend = x - Math.min(gutter - 8, 12 + 9 * (span - 1));
      var state = e.met ? "met" : "wait";
      add("path", {
        "class": "arc " + state,
        d: "M" + x + " " + y1 + " C" + bend + " " + y1 + " " + bend + " " +
           y2 + " " + x + " " + y2
      });
      add("circle", {"class": "arc-end " + state, cx: x, cy: y2, r: 2.6});
    });
  }
  draw();
  window.addEventListener("resize", draw);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
})();
"""


def _notes(values: list[str]) -> dict[str, str]:
    notes: dict[str, str] = {}
    for value in values:
        slug, sep, text = value.partition("=")
        if not sep or not slug.strip() or not text.strip():
            raise UsageError(f"--note `{value}` is not `<slug>=<text>`")
        notes[slug.strip()] = text.strip()
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--headline")
    parser.add_argument("--summary")
    parser.add_argument("--note", action="append", default=[], metavar="SLUG=TEXT")
    parser.add_argument("--target", metavar="SLUG")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--fragment", action="store_true")
    args = parser.parse_args(argv)
    try:
        page = build(args.root, args.target, _notes(args.note))
    except UsageError as error:
        print(f"progress: {error}", file=sys.stderr)
        return 2
    page_html = render(
        page,
        headline=args.headline,
        summary=args.summary,
        generated=args.date,
        fragment=args.fragment,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page_html, encoding="utf-8")
    print(f"progress: wrote {args.out} ({len(page.features)} features)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
