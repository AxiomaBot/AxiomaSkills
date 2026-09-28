#!/usr/bin/env python3
"""Render a project's roadmap progress as one self-contained HTML page.

The ``progress`` skill (``skills/progress/SKILL.md``) runs this so the page
looks the same on every run and no part of the layout is re-derived by
prompt. It reads the files the other skills keep current and writes one HTML
file; it never edits the project.

What it reads:

* ``roadmap.md`` -- the H1 for the project name, the ``## Done`` rows, and the
  ``## Features`` rows with their optional ``After`` column.
* ``docs/features/<slug>/feature.md`` for every row that links a folder: the
  frontmatter ``status`` (shown when it disagrees with the roadmap row) and
  ``depends-on``, the task boxes under each chunk heading, and the sign-off
  line under ``## Test checkpoint``.
* ``docs/features/<slug>/manual_tests.md``: the top-level ``- [ ]`` and
  ``- [x]`` items under each ``##`` checkpoint heading, and its sign-off line.

What a feature waits on is its ``depends-on`` entries plus its ``After``
entries, each feature counted once. A ``<feature>/<chunk>`` entry is met when
every task box under that chunk's heading is ticked or its feature is
``built`` or ``done``; a bare ``<feature>`` entry waits for the whole feature.

The page has two parts. **Shipped** lists the ``## Done`` rows in table order.
**Ahead** lays the other rows out in waves: wave 1 is every feature with
nothing unmet to wait on, and each later wave waits on something in an
earlier one, so features in the same wave can be built in parallel. A line
joins a feature to what waits on it in the very next wave; every other
dependency is a chip only, because a line that skipped a wave would pass
behind the cards between and read as an edge it is not. What a feature waits
on from Shipped is met by definition and shown only as a chip. A roadmap with no
``After`` column has declared no order between outlined features, so Ahead
falls back to table order, one feature per row, and says so. A cycle cannot
hang the layout: a feature met again while its own wave is being worked out
counts as wave 1 (``workflow check`` reports the cycle itself).

The table, section and frontmatter parsers are the ``workflow`` skill's own,
loaded from ``workflow_check.py`` by path, so anything the layout check
accepts is read the same way here.

The headline, summary and per-feature notes come from the caller. Everything
printed from the repository or the arguments is HTML-escaped.

Exit status is 0 when the page was written and 2 on a usage error: no
``roadmap.md``, or a ``--target`` or ``--note`` naming a feature the page does
not show. ``--target`` ends the page at that row of ``## Features``; rows
after it in the table are left off, and the page says how many.

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
    after: list[str] = field(default_factory=list)
    folder_status: str | None = None
    checkpoints: list[Checkpoint] = field(default_factory=list)
    signed_off: str | None = None
    depends: list[Dependency] = field(default_factory=list)
    note: str | None = None
    text: str | None = None

    @property
    def kind(self) -> str:
        """The status as one of ``STATUSES``; anything else styles as ``idea``."""
        status = self.status.lower()
        return status if status in wc.STATUSES else "idea"


@dataclass
class Page:
    project: str
    features: list[Feature]
    ordered: bool = False
    """True when ``## Features`` has an ``After`` column to lay waves out by."""
    target: str | None = None
    hidden: int = 0
    """How many ``## Features`` rows after ``target`` the page leaves off."""


def _cell(row: dict[str, str], key: str, position: int) -> str:
    """A cell by header name, falling back to its usual position."""
    if key in row:
        return row[key]
    values = list(row.values())
    return values[position] if len(values) > position else ""


def _feature(row: dict[str, str], done: bool) -> Feature | None:
    first = _cell(row, "feature", 0)
    if not first:
        return None
    link_match = wc.ROW_LINK.match(first)
    name = link_match.group(1) if link_match else first.strip("`")
    return Feature(
        slug=wc.row_slug(first),
        name=name,
        status="done" if done else _cell(row, "status", 1),
        shipped=_cell(row, "shipped", 1) if done else None,
        line=_cell(row, "one line", 2),
        link=link_match.group(2) if link_match else None,
        after=[] if done else wc.after_entries(row.get("after", "")),
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
    if feature.link is not None:
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
    named = {dep.slug for dep in feature.depends}
    feature.depends += [
        Dependency(slug, slug, None) for slug in feature.after if slug not in named
    ]


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
    feature_rows = wc.table(parts.get("features", ""))
    features = [
        feature
        for row in wc.table(parts.get("done", ""))
        if (feature := _feature(row, done=True))
    ] + [feature for row in feature_rows if (feature := _feature(row, done=False))]
    for feature in features:
        _read_folder(root, feature)
    _resolve(features)

    page = Page(project, features, ordered=any("after" in row for row in feature_rows))
    if target is not None:
        slugs = [feature.slug for feature in features]
        if target not in slugs or features[slugs.index(target)].kind == "done":
            raise UsageError(f"--target `{target}` is not a row in `## Features`")
        page.features = features[: slugs.index(target) + 1]
        page.target = target
        page.hidden = len(features) - len(page.features)
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


def waves(page: Page) -> list[list[int]]:
    """Indices of the features ahead, grouped into waves (see the docstring)."""
    features = page.features
    ahead = [i for i, feature in enumerate(features) if feature.kind != "done"]
    if not page.ordered:
        return [[i] for i in ahead]
    level: dict[int, int] = {}

    def level_of(i: int, seen: frozenset[int]) -> int:
        if i in level:
            return level[i]
        if i in seen:
            return 0
        blockers = [
            dep.upstream
            for dep in features[i].depends
            if dep.upstream is not None
            and not dep.met
            and features[dep.upstream].kind != "done"
        ]
        value = 1 + max((level_of(up, seen | {i}) for up in blockers), default=-1)
        level[i] = value
        return value

    grouped: dict[int, list[int]] = {}
    for i in ahead:
        grouped.setdefault(level_of(i, frozenset()), []).append(i)
    return [grouped[key] for key in sorted(grouped)]


def inline(text: str) -> str:
    """Escape ``text`` and keep the three Markdown marks the roadmap uses."""
    out = html.escape(MD_LINK.sub(r"\1", text))
    out = CODE_SPAN.sub(r"<code>\1</code>", out)
    return BOLD.sub(r"<b>\1</b>", out)


def _pill(feature: Feature, is_target: bool) -> str:
    kind = feature.kind
    css = "done" if kind == "done" else "flight" if kind in IN_FLIGHT else "later"
    label = "Done" if kind == "done" else feature.status or kind
    pill = f'<span class="pill {css}">{html.escape(label)}</span>'
    if is_target:
        pill += '<span class="pill target">Target</span>'
    return pill


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


def _after_html(feature: Feature) -> str:
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
        '<div class="after"><span class="after-label">After</span>'
        + "".join(chips)
        + "</div>"
    )


def _card(feature: Feature, position: int, focus: bool, target: bool) -> str:
    classes = ["card", f"k-{feature.kind}"]
    if focus:
        classes.append("focus")
    if target:
        classes.append("target")
    done = feature.kind == "done"
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
    after = "" if done else _after_html(feature)
    return (
        f'<article class="{" ".join(classes)}" data-i="{position}">'
        '<div class="card-top">'
        f'<span class="name">{html.escape(feature.name)}</span>'
        f'<span class="pills">{_pill(feature, target)}</span></div>'
        f"{line}{mismatch}{after}{_checkpoint_html(feature)}{note}{shipped}"
        "</article>"
    )


def _wave_label(number: int, size: int, ordered: bool) -> str:
    if not ordered:
        return ""
    lead = "Now" if number == 1 else f"Wave {number}"
    tail = f" &middot; {size} in parallel" if size > 1 else ""
    return f'<p class="wave-label">{lead}{tail}</p>'


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
    done = [i for i, f in enumerate(features) if f.kind == "done"]
    flight = [i for i, f in enumerate(features) if f.kind in IN_FLIGHT]
    grouped = waves(page)
    focus = set(flight or (grouped[0] if grouped else []))

    wave_of = {i: number for number, wave in enumerate(grouped) for i in wave}
    links = [
        {"from": dep.upstream, "to": i, "met": dep.met}
        for i in sorted(wave_of)
        for dep in features[i].depends
        if dep.upstream in wave_of and wave_of[i] - wave_of[dep.upstream] == 1
    ]
    distance = ""
    if page.ordered and grouped:
        unit = "wave" if len(grouped) == 1 else "waves"
        end = f"to {html.escape(features[-1].name)}" if page.target else "ahead"
        distance = f" &middot; {len(grouped)} {unit} {end}"

    segments = "".join(
        '<span class="seg '
        + ("done" if f.kind == "done" else "flight" if f.kind in IN_FLIGHT else "later")
        + f'" title="{html.escape(f.name)}"></span>'
        for f in features
    )
    shipped_html = ""
    if done:
        shipped_html = (
            '<section class="part"><h2>Shipped</h2><div class="shipped">'
            + "".join(_card(features[i], i, False, False) for i in done)
            + "</div></section>"
        )
    ahead_html = ""
    if grouped:
        fallback = (
            ""
            if page.ordered
            else '<p class="hint">roadmap.md has no <code>After</code> column, so '
            "this is table order, not a dependency order. Add one to show what "
            "can be built in parallel.</p>"
        )
        legend = (
            '<p class="hint legend"><svg width="46" height="10" aria-hidden="true">'
            '<path class="link met" d="M2 5 H20"/>'
            '<path class="link wait" d="M26 5 H44"/></svg>'
            "Lines run from a feature to what waits on it in the next wave: "
            "solid when met, dashed while waiting. Farther edges are chips "
            "only.</p>"
            if links
            else ""
        )
        left_off = ""
        if page.hidden:
            noun = "feature" if page.hidden == 1 else "features"
            left_off = (
                f'<p class="hint">{page.hidden} {noun} after '
                f"{html.escape(features[-1].name)} in roadmap.md "
                "not shown.</p>"
            )
        rows = "".join(
            '<div class="wave">'
            + _wave_label(number, len(wave), page.ordered)
            + '<div class="wave-cards">'
            + "".join(
                _card(features[i], i, i in focus, features[i].slug == page.target)
                for i in wave
            )
            + "</div></div>"
            for number, wave in enumerate(grouped, 1)
        )
        ahead_html = (
            f'<section class="part"><h2>Ahead</h2>{fallback}{legend}'
            f'<div class="waves"><svg class="links" aria-hidden="true"></svg>'
            f"{rows}</div>{left_off}</section>"
        )

    title = f"{page.project} Roadmap"
    lead = headline or f"{len(done)} of {total} features done."
    dek = f'<p class="dek">{inline(summary)}</p>' if summary else ""
    body = (
        f"<title>{html.escape(title)}</title>\n"
        f"{FONTS}\n<style>{CSS}</style>\n"
        '<main class="page">'
        f'<p class="eyebrow">{html.escape(page.project)} &middot; progress</p>'
        f"<h1>{inline(lead)}</h1>{dek}"
        '<section class="progress" aria-label="Overall progress">'
        '<div class="progress-head"><span class="label">Features</span>'
        f'<span class="count"><b>{len(done)}</b> of {total} done'
        f" &middot; {len(flight)} in flight{distance}</span></div>"
        f'<div class="segments" style="--n:{max(total, 1)}">{segments}</div>'
        f"</section>{shipped_html}{ahead_html}"
        "<footer><span>From roadmap.md and docs/features/</span>"
        f"<span>{html.escape(generated)}</span></footer></main>\n"
        '<script type="application/json" id="progress-links">'
        f"{json.dumps(links)}</script>\n"
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
  --warn: #8a6d00; --warn-soft: #f5ecc4;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14181a; --surface: #1b211d; --surface-muted: #232a25;
    --border: #303a33; --text: #eef1ee; --text-muted: #97a29a;
    --accent: #e2934f; --accent-ink: #f4b878; --accent-soft: #3a2c1c;
    --success: #59c393; --success-soft: #1c3327;
    --warn: #e6c65c; --warn-soft: #36301a;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #14181a; --surface: #1b211d; --surface-muted: #232a25;
  --border: #303a33; --text: #eef1ee; --text-muted: #97a29a;
  --accent: #e2934f; --accent-ink: #f4b878; --accent-soft: #3a2c1c;
  --success: #59c393; --success-soft: #1c3327;
  --warn: #e6c65c; --warn-soft: #36301a;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.5 'IBM Plex Sans', system-ui, -apple-system, sans-serif;
  padding: 40px 16px 64px;
}
.page { max-width: 820px; margin: 0 auto; }
code {
  font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .92em;
  background: var(--surface-muted); padding: 0 .3em; border-radius: 4px;
}
.eyebrow, .label, .cp-title, .after-label, .pill, .meta, .count, .cp-count,
.wave-label, h2, footer {
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
h2 {
  font-size: 12px; font-weight: 600; letter-spacing: .12em;
  text-transform: uppercase; color: var(--text-muted); margin: 0 0 12px;
}
.dek { color: var(--text-muted); font-size: 15px; max-width: 60ch; margin: 0 0 24px; }
.progress {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px 18px; margin: 8px 0 0;
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
.part { margin-top: 36px; }
.shipped { display: flex; flex-direction: column; gap: 10px; }
.hint {
  display: flex; align-items: center; gap: 8px; margin: -4px 0 14px;
  font-size: 12px; color: var(--text-muted);
}
.hint svg { flex: none; }
.waves + .hint { margin: 14px 0 0; }
.waves { position: relative; display: flex; flex-direction: column; gap: 40px; }
.links {
  position: absolute; left: 0; top: 0; overflow: visible; pointer-events: none;
}
.link { fill: none; stroke-width: 1.4; }
.link.met { stroke: var(--success); }
.link.wait { stroke: var(--accent); stroke-dasharray: 4 3; }
.link-end.met { fill: var(--success); }
.link-end.wait { fill: var(--accent); }
@media (max-width: 600px) {
  /* Cards stack in one column here, so a line would run behind the cards
     of its own wave; the After chips carry every edge on their own. */
  .links, .legend { display: none; }
}
.wave { position: relative; }
.wave-label {
  position: relative; display: inline-block; margin: 0 0 8px;
  padding-right: 8px; background: var(--bg); font-size: 11px;
  letter-spacing: .06em; text-transform: uppercase; color: var(--text-muted);
}
.wave-cards {
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}
.card {
  position: relative; background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px;
  display: flex; flex-direction: column; gap: 8px;
}
.card.focus {
  border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent);
}
.card.target { border-color: var(--text); }
.card-top {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 8px;
}
.name { font-weight: 600; font-size: 15px; overflow-wrap: anywhere; }
.pills { display: flex; gap: 6px; flex-wrap: wrap; }
.k-done .name::before { content: "\\2713  "; color: var(--success); }
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
.after { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.after-label { font-size: 11px; color: var(--text-muted); }
.chip {
  font-size: 12px; padding: 2px 8px; border-radius: 6px;
  border: 1px solid transparent; overflow-wrap: anywhere;
}
.chip.met { color: var(--success); background: var(--success-soft); }
.chip.wait { color: var(--accent-ink); background: var(--accent-soft); }
.chip.warn { align-self: flex-start; color: var(--warn); background: var(--warn-soft); }
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
  margin: 0; padding: 8px 12px; border-radius: 0 6px 6px 0;
  background: var(--surface-muted); border-left: 3px solid var(--accent);
  font-size: 13px;
}
footer {
  margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--border);
  display: flex; justify-content: space-between; flex-wrap: wrap; gap: 6px;
  font-size: 11.5px; color: var(--text-muted);
}
"""

JS = """
(function () {
  var data = document.getElementById("progress-links");
  var box = document.querySelector(".waves");
  var svg = box && box.querySelector(".links");
  if (!data || !svg) return;
  var links = JSON.parse(data.textContent);
  if (!links.length) return;
  var NS = "http://www.w3.org/2000/svg";
  function add(tag, attrs) {
    var el = document.createElementNS(NS, tag);
    for (var k in attrs) el.setAttribute(k, attrs[k]);
    svg.appendChild(el);
  }
  function spread(key) {
    var seen = {}, slot = [];
    links.forEach(function (l) { seen[l[key]] = (seen[l[key]] || 0) + 1; });
    var used = {};
    links.forEach(function (l, n) {
      var k = l[key]; used[k] = (used[k] || 0) + 1;
      slot[n] = (used[k] - 1 - (seen[k] - 1) / 2) * 12;
    });
    return slot;
  }
  var out = spread("from"), into = spread("to");
  function draw() {
    while (svg.lastChild) svg.removeChild(svg.lastChild);
    var origin = box.getBoundingClientRect();
    svg.setAttribute("width", origin.width);
    svg.setAttribute("height", origin.height);
    links.forEach(function (l, n) {
      var a = box.querySelector('[data-i="' + l.from + '"]');
      var b = box.querySelector('[data-i="' + l.to + '"]');
      if (!a || !b) return;
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      var x1 = ra.left + ra.width / 2 + out[n] - origin.left;
      var y1 = ra.bottom - origin.top;
      var x2 = rb.left + rb.width / 2 + into[n] - origin.left;
      var y2 = rb.top - origin.top;
      if (y2 - y1 < 12) return;
      var mid = (y1 + y2) / 2, state = l.met ? "met" : "wait";
      add("path", {
        "class": "link " + state,
        d: "M" + x1 + " " + y1 + " C" + x1 + " " + mid + " " + x2 + " " +
           mid + " " + x2 + " " + (y2 - 3)
      });
      add("circle", {"class": "link-end " + state, cx: x2, cy: y2 - 3, r: 2.6});
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
