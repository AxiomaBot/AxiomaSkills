---
description: Render the roadmap as one HTML page on demand — what shipped, what is in flight, each feature's manual-checkpoint progress, and the depends-on graph — then publish it or hand over the file. Read-only.
argument-hint: "[<target-feature>]"
---

# Progress — the roadmap as a page

**Tier:** coding (floor sonnet) — stop if this session is below it; never
switch the session down.

Draw where the project stands, from the files the other skills keep current.
**This skill writes nothing to the project.** It writes one HTML file outside
the repository and hands it over.

Target: `$ARGUMENTS`. If it names a feature, the page ends at that feature
and marks it as the destination (for "from here to go-live", say). If it is
empty, the page shows the whole roadmap. The user may name the end point in
words ("to go-live", "to v1"). Map that to the roadmap row it means. If two
rows could fit, ask when attended; unattended, leave the target off and say
so.

## What the page shows, and where each part comes from

`${CLAUDE_PLUGIN_ROOT}/skills/progress/scripts/progress.py` does all the
reading and drawing. Its docstring is the contract, so don't re-derive a rule
from the files by hand.

- Every row of `roadmap.md` → `## Done` and then `## Features`, in table
  order, with its status and one-line description.
- **Manual checkpoint progress**: ticked out of total top-level items per
  `##` checkpoint in each feature's `manual_tests.md`, and the sign-off line.
- **The dependency graph**: an arc from each feature to what its
  `depends-on` names, solid when met and dashed while waiting. Only features
  with a folder carry `depends-on`, so an `outlined` feature has no arcs.
  That is the roadmap's actual state, not a gap in the page.
- A **status disagreement** between a `roadmap.md` row and its `feature.md`
  shows as a chip on that feature. The page reports the disagreement but
  can't say which file is right.

The page does not show chunk-level build progress, dates or forecasts, and it
has nothing that isn't in those files.

## Steps

1. **Read, don't write.** Read `roadmap.md`. Then read `feature.md` and
   `manual_tests.md` for each feature in flight (`planned`, `building`,
   `built`) and for the most recently done one. Run `git log --oneline -15`
   to see what just landed. Nothing else is needed.

2. **Write the words.** These are the only judgment in this skill, and every
   fact in them has to come from a file you just read:
   - `--headline`: one sentence of current state, in plain words, around
     70 characters at most. Name the last thing that finished and the
     distance left, e.g. *"Burn-in gate cleared. Seven features to
     go-live."* Invent nothing, and don't cheerlead.
   - `--summary`: one to three sentences covering what just finished, what
     is next, and what that next item waits on.
   - `--note <slug>=<text>`, **at most three**: facts the page can't show
     otherwise, such as a verdict, a measured number against its limit, or a
     condition attached to a sign-off. Copy each one from the file that
     records it (an ADR, a `manual_tests.md` result). A note is optional.
     Leave it out rather than pad it.

3. **Render** with the project's own Python (see `CLAUDE.md` → Commands; the
   script is stdlib-only):

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/progress/scripts/progress.py \
     --root . --out <path> [--target <slug>] \
     --headline '<headline>' --summary '<summary>' [--note '<slug>=<text>' ...]
   ```

   - Put `<path>` in the session's scratchpad or temp directory, **never
     inside the repository**, unless the user names a path. A generated page
     in the tree is an untracked file for the next skill to trip over.
   - Add `--fragment` when the page will be published through a tool that
     wraps it in its own document skeleton (an HTML artifact tool does).
     Without it the file is a complete document to open in a browser.
   - Quote each argument for the shell. A headline with an apostrophe
     inside single quotes breaks the command.
   - Exit 2 means a bad argument or no `roadmap.md`, and the message names
     it. Fix the argument; never edit the project to fit the script.

4. **Hand it over.** If this session has a tool that publishes an HTML page
   (an Artifact tool, for example), publish the file and give the link.
   Within one conversation, republish the same path so the link stays the
   same. With no such tool, give the file's path to open in a browser.

5. **Report** in two or three lines: the link or path, and the one fact the
   page leads with. If the page shows a status-disagreement chip, name it and
   point to `/agentic-workflow:workflow check`. Don't fix it here: which file
   is right is the human's call, and this skill writes nothing.
