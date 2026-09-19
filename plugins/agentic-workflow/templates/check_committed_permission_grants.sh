#!/usr/bin/env bash
#
# Fail if this PR widens what an agent may do without asking, anywhere in the
# repo's tracked `.claude/settings*.json` files, compared with <base>.
#
# A committed permission grant is a standing auto-approve for every future agent
# session in the repo — grants belong in untracked local config, never the repo
# (the agentic-workflow plugin's auto-chunk skill never commits one to obtain a
# tool it needs, for exactly this reason). This is the deterministic floor
# under a *diff-only* security review, which sees a settings file only when it
# is in the diff and is poorly placed to weigh what a grant really authorises.
# There is no docs-only or otherwise path-based skip anywhere in this workflow:
# this guard runs on every PR.
#
# WIDENING HAPPENS TWO WAYS, and both are checked.
#
# 1. A GRANT IS ADDED. Five kinds count, because each auto-approves something
#    for every future session and `permissions.allow` is the narrowest:
#
#    allow                      one tool pattern pre-approved.
#    additionalDirectories      filesystem reach outside the project.
#    defaultMode                the blanket setting. `bypassPermissions`,
#                               `dontAsk` and `acceptEdits` each approve a whole
#                               class of action with no allow entry at all, so a
#                               guard reading only `allow` waves through the
#                               broadest grant while blocking the narrowest.
#    enableAllProjectMcpServers a top-level key (a sibling of `permissions`, not
#                               nested under it) auto-approving every MCP server
#                               the project's `.mcp.json` declares. Anything but
#                               a literal `false` counts: `"true"` and `1` are
#                               not booleans but are plainly not "off".
#    enabledMcpjsonServers      the same, named one server at a time. Both run
#                               arbitrary code on every future session.
#
# 2. A RESTRICTION IS WEAKENED. Deleting a `permissions.deny` or
#    `permissions.ask` entry widens the auto-approved surface just as surely as
#    adding an `allow`, and a guard that only counts additions reports "no new
#    permission grants" on a PR that turned a hard deny into a silent yes. So
#    does dropping `defaultMode: "plan"`, which is stricter than the default it
#    falls back to; `disableBypassPermissionsMode`, which forbids the broadest
#    mode outright; or a `disabledMcpjsonServers` entry, which re-permits a
#    named MCP server. Removals are reported separately because the fix differs: an
#    addition is moved to local config, whereas a removal is restored or
#    justified.
#
#    A removal is overridable and an addition is not, because a `deny` whose
#    rule went obsolete has to be deletable, whereas a committed `allow` has no
#    legitimate in-repo form. ALLOW_PERMISSION_WEAKENING=1 is that override, and
#    setting it on the job is itself a reviewable diff.
#
#    RESTRICTIONS ARE ORDERED, so tightening is never reported. `deny` is
#    stronger than `ask`, so an `ask` entry at base is satisfied by an `ask`
#    *or* a `deny` at head -- promoting one to the other is a security
#    improvement and must not fail CI. A `deny` at base needs a `deny` at head,
#    because downgrading it to `ask` really is widening.
#
# PATHS ARE READ AS BYTES. `git ls-files` C-quotes any path holding a
# non-ASCII byte, a newline, a quote or a backslash, so
# `"p\303\266ckages/.claude/settings.json"` matched no pattern and a grant
# inside it was invisible -- a fail-open in a script whose whole contract is the
# opposite. Enumeration is `core.quotePath=false` and NUL-delimited throughout,
# and matching is done in bash rather than by piping through line-oriented
# tools, so a path is never reshaped on its way to the regex.
#
# EVERY TRACKED SETTINGS FILE COUNTS, not only the one at the repo root.
# `packages/app/.claude/settings.json` is a live grant for anyone who opens
# Claude Code in `packages/app`, which in a monorepo is the normal way to work,
# and scoping this guard to the root made that grant invisible.
#
# DELIBERATELY NOT CHECKED: a `hooks` block. Hooks also execute automatically,
# but committing them is the supported way to configure a project rather than a
# way to widen what an agent may approve, so flagging every one would bury the
# signal this guard exists for. If that trade ever stops holding, it belongs in
# a guard of its own with its own name, not bolted on here.
#
# The mode test is an ALLOWLIST (SAFE_DEFAULT_MODES), not a blocklist: a mode
# that ships after this was written fails closed and gets looked at, rather than
# being permitted by an enumeration nobody remembered to update. If a new mode
# genuinely grants nothing, add it there.
#
# THE SCRIPT FAILS CLOSED, ASYMMETRICALLY. Every earlier version swallowed jq's
# stderr and exit status, so a settings file jq could not parse — a stray comment
# making it JSONC, a truncated write — yielded zero lines and the run reported
# "no new permission grants" and exited 0. With jq absent, *every* grant passed.
# A security control that reports success when it could not read its input is
# worse than no control, because the green check is taken as evidence.
#
# The asymmetry is deliberate. An unreadable file at HEAD is this PR's to fix,
# so it is an error. An unreadable file at BASE is already on the main branch,
# and failing on it would fail *every* PR including the one repairing it — a
# deadlock clearable only by pushing straight to main, which is precisely what
# this guard exists to make unnecessary. So a base-side file that cannot be read
# contributes nothing and warns. That stays conservative in both directions:
# base contributing no grants makes every grant at HEAD read as new, and base
# contributing no restrictions means nothing can look removed.
#
# READING IS ONE PATH, NOT FIVE. Four rounds of review found a separate hole in
# each place a file was read: a missing worktree copy skipped, a base-side
# diagnostic raised as an error, an empty file passed, a `jq -e` that rejects a
# valid `null`, a grant value carrying a newline splitting into lines that each
# already existed at base. All the same bug in different clothes, because
# reading was open-coded per caller. Every read now goes through `fields_of`,
# which takes the severity to report at, and one jq pass emits grants and
# restrictions together so the two can never disagree about what a file says.
#
# The comparison is over the UNION across every tracked settings file (base vs.
# head), keyed on the entry itself — not per file path. So renaming/moving a
# settings file, or splitting one into several, never reads unchanged entries as
# added or removed.
#
# Usage: check_committed_permission_grants.sh <base-ref>
set -euo pipefail

base="${1:?usage: check_committed_permission_grants.sh <base-ref>}"

# Run from the repo root, always. `git ls-tree -r` and `git ls-files` are both
# scoped to the current directory, so invoking this from a subdirectory reported
# a repo clean while a grant sat in the root settings file. Moving once here
# fixes every git call below at the same time, and keeps `$f` root-relative so
# `git show` and the work-tree read agree about what a path means.
if ! repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  echo "::error::not inside a git work tree, so this guard cannot enumerate anything. Refusing to report a repo unchanged that it could not inspect." >&2
  exit 1
fi
cd "$repo_root"

if ! command -v jq >/dev/null 2>&1; then
  echo "::error::jq is not installed, so this guard cannot read any settings file. Refusing to report a repo unchanged that it could not inspect; install jq in the job." >&2
  exit 1
fi

# The only `permissions.defaultMode` values that grant nothing. `default` is the
# baseline and neither grants nor restricts; `plan` is stricter than it, so
# losing `plan` is a weakening and it is tracked as a restriction below.
SAFE_DEFAULT_MODES='["default","plan"]'

# One pass emits every side of the comparison, tagged:
#   G  something that grants
#   D  a `deny` entry          (the strongest restriction)
#   A  an `ask` entry          (satisfied at head by an ask OR a deny)
#   P  `defaultMode: "plan"`   (stricter than the default it falls back to)
# Every value goes through `@json`, so one entry is always exactly one line --
# comparison is line-based, and a value containing a newline otherwise
# decomposes into lines that may each already exist at base, letting a string
# absent from base through as "nothing new". `@json` also quotes the value in
# the report, showing the exact string.
JQ_FIELDS='
  ( (.permissions.allow // [])[]                 | "G allow: \(@json)" ),
  ( (.permissions.additionalDirectories // [])[] | "G additionalDirectories: \(@json)" ),
  ( (.permissions.defaultMode // empty)
      | select(. as $mode | $safe | index($mode) == null)
      | "G defaultMode: \(@json)" ),
  ( (.enableAllProjectMcpServers // empty)
      | select(. != false)
      | "G enableAllProjectMcpServers: \(@json)" ),
  ( (.enabledMcpjsonServers // [])[]             | "G enabledMcpjsonServers: \(@json)" ),
  ( (.permissions.deny // [])[]                  | "D \(@json)" ),
  ( (.permissions.ask // [])[]                   | "A \(@json)" ),
  ( (.permissions.defaultMode // empty)
      | select(. == "plan")
      | "P \(@json)" ),
  ( (.permissions.disableBypassPermissionsMode // empty)
      | select(. != false)
      | "B \(@json)" ),
  ( (.disabledMcpjsonServers // [])[]            | "X \(@json)" )
'

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Any depth, not just the repo root: `packages/app/.claude/settings.json` is a
# live grant for anyone working in that subdirectory.
settings_re='(^|/)\.claude/settings[^/]*\.json$'

# Emit a workflow annotation. GitHub reads these off stderr, so a base-side
# problem must NOT use `error`, or a passing run posts a red annotation anyway.
note() {               # $1 = error|warning, $2 = message
  echo "::${1}::${2}" >&2
}

# Write one settings file's tagged entries to stdout.
#
# NEVER call this on the right of a pipe: `exit` there runs in a subshell and
# leaves the script running. Every caller redirects to a file and checks the
# return value. The caller also chooses the severity, because the same
# unreadable file is fatal at HEAD and only a warning at BASE.
fields_of() {          # $1 = path, $2 = label, $3 = error|warning
  local count
  # `jq -s length`, not `jq -e .`: `-e` takes its status from the output value,
  # so a valid top-level `null` or `false` would be rejected as a parse error.
  # Counting values separates the three cases that matter (broken syntax, no
  # value at all, a real document) and keeps jq's own diagnostic.
  if ! count="$(jq -s 'length' "$1" 2>"$tmp/jq_err")"; then
    note "$3" "${2} is not valid JSON, so this guard cannot tell what it permits: $(tr '\n' ' ' < "$tmp/jq_err")"
    return 1
  fi
  if [ "$count" -eq 0 ]; then
    note "$3" "${2} holds no JSON value at all (an empty file, or a truncated write), so this guard cannot tell what it permits."
    return 1
  fi
  if ! jq -r --argjson safe "$SAFE_DEFAULT_MODES" "$JQ_FIELDS" "$1" 2>"$tmp/jq_err"; then
    note "$3" "${2} is valid JSON, but this guard could not read its permission fields. Check the value types: allow, deny, ask, additionalDirectories and enabledMcpjsonServers must be arrays, and defaultMode a string. $(tr '\n' ' ' < "$tmp/jq_err")"
    return 1
  fi
}

# Pull one tag's values out of a tagged entry list, each prefixed with the
# SCOPE it was found in: the directory holding the `.claude` folder, empty for
# the repo root.
#
# Any-depth discovery made the path meaningful. Keyed on the entry alone, an
# `allow` moved from `packages/app/.claude/` up to the root read as unchanged
# while actually being promoted repo-wide, and a `deny` moved the other way read
# as unchanged while being demoted to one subdirectory. Scope-keying is what
# makes those visible; `covers` below is what keeps a legitimate move from
# being reported.
# Lines arrive as `<tag>\t<scope>\t<value>`; this yields `<scope>\t<value>`
# for one tag. A value is `@json`, so it can hold no literal tab.
tagged() {             # $1 = tagged file, $2 = tag letter, $3 = destination
  awk -F'\t' -v t="$2" '$1 == t { print $2 "\t" $3 }' "$1" | sort -u > "$3"
}

# The scope a settings path belongs to: everything before its `.claude/`.
scope_of() {           # $1 = path
  local s="${1%/.claude/*}"
  [ "$s" = "$1" ] && s=""       # the path began with .claude/, so: root
  printf '%s' "$s"
}

# Rewrite `<tag> <value>` lines as `<tag>\t<scope>\t<value>`.
#
# The scope arrives through the environment, never spliced into a sed or awk
# program: a directory called `a&b` would otherwise expand `&` to the matched
# text, and a `|` would end the expression outright. `ENVIRON` does no escape
# processing, unlike `awk -v`, so an arbitrary path byte survives intact.
scope_lines() {        # $1 = tagged file, $2 = scope
  GUARD_SCOPE="$2" awk '{
    print substr($0, 1, 1) "\t" ENVIRON["GUARD_SCOPE"] "\t" substr($0, 3)
  }' "$1"
}

# Entries in $2 that nothing in $1 covers.
#
# An entry covers another when the value matches and its scope is the same or an
# ANCESTOR of it, because a settings file applies to its own subtree. So moving a
# `deny` from `packages/app` up to `packages` or to the root still covers what it
# replaced -- a tightening -- while moving it down covers nothing, and an `allow`
# promoted upward is not covered by the narrower one it came from.
uncovered() {          # $1 = covering entries, $2 = entries to test
  # Discriminate on FILENAME, not `NR == FNR`: when the covering file is empty
  # awk never reads a record from it, so NR and FNR both restart on the second
  # file and every entry reads as already-seen -- which silently passed every
  # grant in a repo whose base had none.
  awk -F'\t' -v cov="$1" '
    function parent(p,   i) {
      for (i = length(p); i > 0; i--)
        if (substr(p, i, 1) == "/") return substr(p, 1, i - 1)
      return ""
    }
    FILENAME == cov { seen[$1 SUBSEP $2] = 1; next }
    {
      s = $1
      while (1) {
        if ((s SUBSEP $2) in seen) next
        if (s == "") break
        s = parent(s)
      }
      print
    }
  ' "$1" "$2"
}

# Every tracked settings path, NUL-delimited in and out. Matching happens in
# bash so the path never passes through a line-oriented tool that would reshape
# one containing a newline.
collect_settings() {   # $1 = NUL-delimited file list, $2 = destination
  local f
  : > "$2"
  while IFS= read -r -d '' f; do
    if [[ "$f" =~ $settings_re ]]; then
      printf '%s\0' "$f" >> "$2"
    fi
  done < "$1"
}

# The HEAD copy of a tracked file: the work tree if present, else the index.
#
# `[ -f ]` alone was a silent skip, and under an `actions/checkout` sparse
# checkout excluding `.claude` it made this guard a permanent green no-op: base
# is read from git objects, head was read from disk, so head found nothing. The
# index always holds the blob for a tracked path. `cat` is tested, not assumed:
# in a condition context `set -e` is suspended, so an unreadable-but-present
# copy used to report a successful read and the fallback never ran.
head_content() {       # $1 = path, $2 = destination
  if [ -f "$1" ] && cat "$1" > "$2" 2>/dev/null; then
    return 0
  fi
  git show ":$1" > "$2" 2>/dev/null
}

# --- BASE: every tracked settings file at <base>.
# A bad <base-ref> is an error; matching nothing is not.
if ! git -c core.quotePath=false ls-tree -r -z --name-only "$base" > "$tmp/base_all" 2>/dev/null; then
  note error "could not list tracked files at ${base} (base-side enumeration); this guard will not report a repo unchanged that it could not enumerate."
  exit 1
fi
collect_settings "$tmp/base_all" "$tmp/base_files"
: > "$tmp/base_tagged"
while IFS= read -r -d '' f; do
  if ! git show "$base:$f" > "$tmp/blob" 2>/dev/null; then
    note warning "could not read ${f} at ${base} (a blobless or partial clone does this), so it is treated as permitting nothing: every grant in this PR's copy will read as new, and nothing it restricted can look removed."
    continue
  fi
  if fields_of "$tmp/blob" "${f} (at ${base})" warning > "$tmp/blob_fields"; then
    scope_lines "$tmp/blob_fields" "$(scope_of "$f")" >> "$tmp/base_tagged"
  else
    note warning "${f} is already unreadable at ${base}, so it is treated as permitting nothing. Repair it on the base branch."
  fi
done < "$tmp/base_files"

# --- HEAD: the same set in this PR's own tree.
# Enumeration failing is not the same as finding nothing.
if ! git -c core.quotePath=false ls-files -z > "$tmp/head_all"; then
  note error "could not list tracked files in the work tree (head-side enumeration); this guard will not report a repo unchanged that it could not enumerate."
  exit 1
fi
collect_settings "$tmp/head_all" "$tmp/head_files"
: > "$tmp/head_tagged"
while IFS= read -r -d '' f; do
  if ! head_content "$f" "$tmp/head_blob"; then
    note error "${f} is tracked but its content could not be read from the work tree or the index, so this guard cannot tell what it permits."
    exit 1
  fi
  fields_of "$tmp/head_blob" "$f" error > "$tmp/head_fields" || exit 1
  scope_lines "$tmp/head_fields" "$(scope_of "$f")" >> "$tmp/head_tagged"
done < "$tmp/head_files"

for side in base head; do
  for tag in G D A P B X; do
    tagged "$tmp/${side}_tagged" "$tag" "$tmp/${side}_${tag}"
  done
done

# Grants at HEAD that nothing at BASE covers.
uncovered "$tmp/base_G" "$tmp/head_G" | cut -f2- > "$tmp/added"

# Restrictions weakened. `deny` needs a `deny`; `ask` is satisfied by either, so
# promoting an ask to a deny is a tightening and passes.
sort -u "$tmp/head_A" "$tmp/head_D" -o "$tmp/head_A_or_D"
uncovered "$tmp/head_D" "$tmp/base_D" | cut -f2- | sed 's/^/deny: /' > "$tmp/removed"
uncovered "$tmp/head_A_or_D" "$tmp/base_A" | cut -f2- | sed 's/^/ask: /' >> "$tmp/removed"
uncovered "$tmp/head_P" "$tmp/base_P" | cut -f2- | sed 's/^/defaultMode: /' >> "$tmp/removed"
uncovered "$tmp/head_B" "$tmp/base_B" | cut -f2- | sed 's/^/disableBypassPermissionsMode: /' >> "$tmp/removed"
uncovered "$tmp/head_X" "$tmp/base_X" | cut -f2- | sed 's/^/disabledMcpjsonServers: /' >> "$tmp/removed"

if [ ! -s "$tmp/added" ] && [ ! -s "$tmp/removed" ]; then
  echo "OK: no permission grant added and no restriction weakened across tracked .claude/settings*.json."
  exit 0
fi

# Report each new grant against the head file(s) it appears in, for the fixer.
if [ -s "$tmp/added" ]; then
  while IFS= read -r -d '' f; do
    head_content "$f" "$tmp/head_blob" || continue
    fields_of "$tmp/head_blob" "$f" error > "$tmp/f_tagged" || exit 1
    scope_lines "$tmp/f_tagged" "$(scope_of "$f")" > "$tmp/f_scoped"
    tagged "$tmp/f_scoped" G "$tmp/f_G_scoped"
    cut -f2- "$tmp/f_G_scoped" | sort -u > "$tmp/f_G"
    sort -u "$tmp/added" -o "$tmp/added"
    f_new="$(comm -12 "$tmp/f_G" "$tmp/added" || true)"
    if [ -n "$f_new" ]; then
      echo "::error file=$f::New permission grant(s) committed to $f — move them to untracked local config (AGENTS.md: never commit a permission grant)." >&2
      sed 's/^/  /' <<<"$f_new" >&2
    fi
  done < "$tmp/head_files"
fi

# A weakened restriction has no head file to point at, so it is reported once.
#
# Unlike an added grant, a removal is sometimes exactly what a PR is for: a deny
# whose rule is obsolete has to be deletable. Saying "say in the PR why" while
# exiting 1 regardless left that PR permanently red with no way through, which
# is the deadlock this script's own header argues against. So the escape hatch
# is real and deliberately awkward: setting ALLOW_PERMISSION_WEAKENING=1 in the
# workflow is itself a reviewable diff, which is the visibility the guard wants.
if [ -s "$tmp/removed" ]; then
  if [ "${ALLOW_PERMISSION_WEAKENING:-0}" = "1" ]; then
    note warning "This PR weakens a restriction that ${base} had, allowed by ALLOW_PERMISSION_WEAKENING=1."
    sed 's/^/  /' "$tmp/removed" >&2
  else
    echo "::error::This PR weakens a restriction that ${base} had, which widens what an agent may do without asking just as an added grant would. Restore it, or — if the removal is the point — set ALLOW_PERMISSION_WEAKENING=1 on this job, which is itself a reviewable change. (Promoting an \`ask\` to a \`deny\` is a tightening and is not reported.)" >&2
    sed 's/^/  /' "$tmp/removed" >&2
    weakened=1
  fi
fi

# An added grant is never overridable: it has no legitimate in-repo form.
if [ -s "$tmp/added" ] || [ "${weakened:-0}" = "1" ]; then
  exit 1
fi
echo "OK: no permission grant added, and the restriction change is allowed by ALLOW_PERMISSION_WEAKENING=1."
exit 0
