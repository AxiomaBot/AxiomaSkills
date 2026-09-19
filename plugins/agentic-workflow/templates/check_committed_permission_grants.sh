#!/usr/bin/env bash
#
# Fail if this PR introduces a permission grant that did not exist anywhere in
# the repo's tracked `.claude/settings*.json` at <base>.
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
# FIVE kinds of grant count, because each auto-approves something for every
# future session and `permissions.allow` is the narrowest of them:
#
#   allow                      one tool pattern pre-approved.
#   additionalDirectories      filesystem reach outside the project.
#   defaultMode                the blanket setting. `bypassPermissions`,
#                              `dontAsk` and `acceptEdits` each approve a whole
#                              class of action with no allow entry at all, so a
#                              guard reading only `allow` waves through the
#                              broadest grant while blocking the narrowest.
#   enableAllProjectMcpServers a top-level key (a sibling of `permissions`, not
#                              nested under it) auto-approving every MCP server
#                              the project's `.mcp.json` declares. Anything but
#                              a literal `false` counts: `"true"` and `1` are
#                              not booleans but are plainly not "off", and a
#                              guard matching only `true` let either through.
#   enabledMcpjsonServers      the same, named one server at a time. Both run
#                              arbitrary code on every future session.
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
# making it JSONC, a truncated write — yielded zero grant lines and the run
# reported "no new permission grants" and exited 0. With jq absent from the
# runner entirely, *every* grant passed. A security control that reports success
# when it could not read its input is worse than no control, because the green
# check is taken as evidence.
#
# The asymmetry matters and is not an oversight. An unreadable file at HEAD is
# this PR's to fix, so it is an error. An unreadable file at BASE is already on
# the main branch, and failing on it would fail *every* PR including the one
# repairing it — a deadlock clearable only by pushing straight to main, which is
# precisely what this guard exists to make unnecessary. So a base-side file that
# cannot be read contributes no grants and warns. That stays conservative: with
# base contributing nothing, every grant at HEAD reads as newly added.
#
# The comparison is over the UNION of grants across every tracked
# `.claude/settings*.json` (base vs. head), keyed on the grant itself — not per
# file path. So renaming/moving a settings file, or splitting one into several,
# never reads unchanged grants as "new"; only a grant absent from every settings
# file at <base> fails.
#
# Usage: check_committed_permission_grants.sh <base-ref>
#
# READING IS ONE PATH, NOT FIVE. Three rounds of review found a separate hole in
# each place a file was read: a missing worktree copy skipped, a base-side
# diagnostic raised as an error, an empty file passed, a `jq -e` that rejects a
# valid `null`. All the same bug in different clothes, because reading was
# open-coded per caller. Every read now goes through `grants_of`, which takes
# the severity to report at, so base-side stays a warning and head-side an error
# without either caller deciding for itself what "unreadable" means.
set -euo pipefail

base="${1:?usage: check_committed_permission_grants.sh <base-ref>}"

if ! command -v jq >/dev/null 2>&1; then
  echo "::error::jq is not installed, so this guard cannot read any settings file. Refusing to report a repo grant-free that it could not inspect; install jq in the job." >&2
  exit 1
fi

# The only `permissions.defaultMode` values that grant nothing: `default`
# prompts as it normally would, and `plan` is strictly more restrictive.
SAFE_DEFAULT_MODES='["default","plan"]'

# Every value goes through `@json`, so one grant is always exactly one line.
# Comparison is line-based, and a grant string containing a newline otherwise
# decomposes into several lines which may each already exist at base -- letting
# a value absent from base through as "nothing new". `@json` also quotes the
# value in the report, which shows the fixer the exact string.
JQ_GRANTS='
  ( (.permissions.allow // [])[]                 | "allow: \(@json)" ),
  ( (.permissions.additionalDirectories // [])[] | "additionalDirectories: \(@json)" ),
  ( (.permissions.defaultMode // empty)
      | select(. as $mode | $safe | index($mode) == null)
      | "defaultMode: \(@json)" ),
  ( (.enableAllProjectMcpServers // empty)
      | select(. != false)
      | "enableAllProjectMcpServers: \(@json)" ),
  ( (.enabledMcpjsonServers // [])[]             | "enabledMcpjsonServers: \(@json)" )
'

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

settings_re='^\.claude/settings[^/]*\.json$'

# Emit a workflow annotation. GitHub reads these off stderr, so a base-side
# problem must NOT use `error`, or a passing run posts a red annotation anyway.
note() {               # $1 = error|warning, $2 = message
  echo "::${1}::${2}" >&2
}

# Write one settings file's grants to stdout.
#
# NEVER call this on the right of a pipe: `exit` there runs in a subshell and
# leaves the script running. Every caller redirects to a file and checks the
# return value. The caller also chooses the severity, because the same
# unreadable file is fatal at HEAD and only a warning at BASE.
grants_of() {          # $1 = path, $2 = label, $3 = error|warning
  local count
  # `jq -s length`, not `jq -e .`: `-e` takes its status from the output value,
  # so a valid top-level `null` or `false` would be rejected as a parse error.
  # Counting values separates the three cases that matter (broken syntax, no
  # value at all, a real document) and keeps jq's own diagnostic.
  if ! count="$(jq -s 'length' "$1" 2>"$tmp/jq_err")"; then
    note "$3" "${2} is not valid JSON, so this guard cannot tell whether it carries a permission grant: $(tr '\n' ' ' < "$tmp/jq_err")"
    return 1
  fi
  if [ "$count" -eq 0 ]; then
    note "$3" "${2} holds no JSON value at all (an empty file, or a truncated write), so this guard cannot tell whether it carries a permission grant."
    return 1
  fi
  if ! jq -r --argjson safe "$SAFE_DEFAULT_MODES" "$JQ_GRANTS" "$1" 2>"$tmp/jq_err"; then
    note "$3" "${2} is valid JSON, but this guard could not read its permission fields. Check the value types: allow, additionalDirectories and enabledMcpjsonServers must be arrays, and defaultMode a string. $(tr '\n' ' ' < "$tmp/jq_err")"
    return 1
  fi
}

# The HEAD copy of a tracked file: the work tree if present, else the index.
#
# `[ -f ]` alone was a silent skip, and under an `actions/checkout` sparse
# checkout excluding `.claude` it made this guard a permanent green no-op: base
# is read from git objects, head was read from disk, so head found nothing. The
# index always holds the blob for a tracked path.
head_content() {       # $1 = path, $2 = destination
  # `cat` is tested, not assumed: in a condition context `set -e` is suspended,
  # so an unreadable-but-present copy used to report a successful read and the
  # index fallback never ran.
  if [ -f "$1" ] && cat "$1" > "$2" 2>/dev/null; then
    return 0
  fi
  git show ":$1" > "$2" 2>/dev/null
}

# --- BASE: the union of grants across every tracked settings file at <base>.
# A bad <base-ref> is an error; `grep` matching nothing is not.
if ! git ls-tree -r --name-only "$base" -- .claude > "$tmp/base_all" 2>/dev/null; then
  note error "could not list tracked files at ${base} (base-side enumeration); this guard will not report a repo grant-free that it could not enumerate."
  exit 1
fi
grep -E "$settings_re" "$tmp/base_all" | sort -u > "$tmp/base_files" || true
: > "$tmp/base_grants"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  if ! git show "$base:$f" > "$tmp/blob" 2>/dev/null; then
    note warning "could not read ${f} at ${base} (a blobless or partial clone does this), so it is treated as granting nothing and every grant in this PR's copy will read as new."
    continue
  fi
  if grants_of "$tmp/blob" "${f} (at ${base})" warning > "$tmp/blob_grants"; then
    cat "$tmp/blob_grants" >> "$tmp/base_grants"
  else
    note warning "${f} is already unreadable at ${base}, so it is treated as granting nothing and every grant in this PR's copy will read as new. Repair it on the base branch."
  fi
done < "$tmp/base_files"
sort -u "$tmp/base_grants" -o "$tmp/base_grants"

# --- HEAD: the same union in this PR's own tree.
# Enumeration failing is not the same as finding nothing.
if ! git ls-files -- .claude > "$tmp/head_all"; then
  note error "could not list tracked files in the work tree (head-side enumeration); this guard will not report a repo grant-free that it could not enumerate."
  exit 1
fi
grep -E "$settings_re" "$tmp/head_all" | sort -u > "$tmp/head_files" || true
: > "$tmp/head_grants"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  if ! head_content "$f" "$tmp/head_blob"; then
    note error "${f} is tracked but its content could not be read from the work tree or the index, so this guard cannot tell whether it carries a permission grant."
    exit 1
  fi
  grants_of "$tmp/head_blob" "$f" error >> "$tmp/head_grants" || exit 1
done < "$tmp/head_files"
sort -u "$tmp/head_grants" -o "$tmp/head_grants"

# Grants present in HEAD but in no settings file at BASE.
comm -13 "$tmp/base_grants" "$tmp/head_grants" > "$tmp/added" || true

if [ ! -s "$tmp/added" ]; then
  echo "OK: no new permission grants across tracked .claude/settings*.json."
  exit 0
fi

# Report each new grant against the head file(s) it appears in, for the fixer.
while IFS= read -r f; do
  [ -n "$f" ] || continue
  head_content "$f" "$tmp/head_blob" || continue
  grants_of "$tmp/head_blob" "$f" error > "$tmp/f_raw" || exit 1
  sort -u "$tmp/f_raw" -o "$tmp/f_grants"
  f_new="$(comm -12 "$tmp/f_grants" "$tmp/added" || true)"
  if [ -n "$f_new" ]; then
    echo "::error file=$f::New permission grant(s) committed to $f — move them to untracked local config (AGENTS.md: never commit a permission grant)." >&2
    sed 's/^/  /' <<<"$f_new" >&2
  fi
done < "$tmp/head_files"

exit 1
