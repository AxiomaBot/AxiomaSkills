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
# FOUR kinds of grant count, because each auto-approves something for every
# future session and `permissions.allow` is the narrowest of them:
#
#   allow                     one tool pattern pre-approved.
#   additionalDirectories     filesystem reach outside the project.
#   defaultMode               the blanket setting. `bypassPermissions`,
#                             `dontAsk` and `acceptEdits` each approve a whole
#                             class of action with no allow entry at all, so a
#                             guard reading only `allow` waves through the
#                             broadest grant while blocking the narrowest.
#   enableAllProjectMcpServers a top-level key (a sibling of `permissions`,
#                             not nested under it) that auto-approves every
#                             MCP server the project's own `.mcp.json`
#                             declares, with no per-server confirmation —
#                             arbitrary code, on every future session, that
#                             nothing above this line would ever see.
#
# The mode test is an ALLOWLIST (SAFE_DEFAULT_MODES), not a blocklist: a mode
# that ships after this was written fails closed and gets looked at, rather than
# being permitted by an enumeration nobody remembered to update. If a new mode
# genuinely grants nothing, add it there.
#
# The comparison is over the UNION of grants across every tracked
# `.claude/settings*.json` (base vs. head), keyed on the grant itself — not per
# file path. So renaming/moving a settings file, or splitting one into several,
# never reads unchanged grants as "new"; only a grant absent from every settings
# file at <base> fails.
#
# Usage: check_committed_permission_grants.sh <base-ref>
set -euo pipefail

base="${1:?usage: check_committed_permission_grants.sh <base-ref>}"

# The only `permissions.defaultMode` values that grant nothing: `default`
# prompts as it normally would, and `plan` is strictly more restrictive.
SAFE_DEFAULT_MODES='["default","plan"]'

# Every grant in one settings file (read from stdin) as a `<kind>: <value>`
# line. Defined once and used for base, for head, and for the per-file report,
# so those three can never disagree about what counts as a grant.
grants() {
  jq -r --argjson safe "$SAFE_DEFAULT_MODES" '
    ( (.permissions.allow // [])[]                 | "allow: \(.)" ),
    ( (.permissions.additionalDirectories // [])[] | "additionalDirectories: \(.)" ),
    ( (.permissions.defaultMode // empty)
        | select(. as $mode | $safe | index($mode) == null)
        | "defaultMode: \(.)" ),
    ( (.enableAllProjectMcpServers // false)
        | select(. == true)
        | "enableAllProjectMcpServers: true" )
  ' 2>/dev/null || true
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

settings_re='^\.claude/settings[^/]*\.json$'

# Union of grants across every tracked .claude/settings*.json at BASE.
git ls-tree -r --name-only "$base" -- .claude 2>/dev/null \
  | grep -E "$settings_re" | sort -u > "$tmp/base_files" || true
: > "$tmp/base_grants"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  git show "$base:$f" 2>/dev/null | grants >> "$tmp/base_grants" || true
done < "$tmp/base_files"
sort -u "$tmp/base_grants" -o "$tmp/base_grants"

# Union of grants across every tracked .claude/settings*.json in HEAD.
git ls-files -- .claude | grep -E "$settings_re" | sort -u > "$tmp/head_files" || true
: > "$tmp/head_grants"
while IFS= read -r f; do
  [ -f "$f" ] || continue
  grants < "$f" >> "$tmp/head_grants" || true
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
  [ -f "$f" ] || continue
  grants < "$f" | sort -u > "$tmp/f_grants" || : > "$tmp/f_grants"
  f_new="$(comm -12 "$tmp/f_grants" "$tmp/added" || true)"
  if [ -n "$f_new" ]; then
    echo "::error file=$f::New permission grant(s) committed to $f — move them to untracked local config (AGENTS.md: never commit a permission grant)." >&2
    sed 's/^/  /' <<<"$f_new" >&2
  fi
done < "$tmp/head_files"

exit 1
