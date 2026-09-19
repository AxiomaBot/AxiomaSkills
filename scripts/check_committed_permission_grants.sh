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
# The comparison is over the UNION of `permissions.allow` entries across every
# tracked `.claude/settings*.json` (base vs. head), keyed on the grant string
# itself — not per file path. So renaming/moving a settings file, or splitting
# one into several, never reads unchanged grants as "new"; only a grant string
# absent from every settings file at <base> fails.
#
# Usage: check_committed_permission_grants.sh <base-ref>
set -euo pipefail

base="${1:?usage: check_committed_permission_grants.sh <base-ref>}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

settings_re='^\.claude/settings[^/]*\.json$'

# Union of allow entries across every tracked .claude/settings*.json at BASE.
git ls-tree -r --name-only "$base" -- .claude 2>/dev/null \
  | grep -E "$settings_re" | sort -u > "$tmp/base_files" || true
: > "$tmp/base_allow"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  git show "$base:$f" 2>/dev/null \
    | jq -r '.permissions.allow // [] | .[]' 2>/dev/null >> "$tmp/base_allow" || true
done < "$tmp/base_files"
sort -u "$tmp/base_allow" -o "$tmp/base_allow"

# Union of allow entries across every tracked .claude/settings*.json in HEAD.
git ls-files -- .claude | grep -E "$settings_re" | sort -u > "$tmp/head_files" || true

# Grants present in HEAD but in no settings file at BASE.
: > "$tmp/head_allow"
while IFS= read -r f; do
  [ -f "$f" ] || continue
  jq -r '.permissions.allow // [] | .[]' "$f" 2>/dev/null >> "$tmp/head_allow" || true
done < "$tmp/head_files"
sort -u "$tmp/head_allow" -o "$tmp/head_allow"
comm -13 "$tmp/base_allow" "$tmp/head_allow" > "$tmp/added" || true

if [ ! -s "$tmp/added" ]; then
  echo "OK: no new permission grants across tracked .claude/settings*.json."
  exit 0
fi

# Report each new grant against the head file(s) it appears in, for the fixer.
while IFS= read -r f; do
  [ -f "$f" ] || continue
  jq -r '.permissions.allow // [] | .[]' "$f" 2>/dev/null | sort -u > "$tmp/f_allow" || : > "$tmp/f_allow"
  f_new="$(comm -12 "$tmp/f_allow" "$tmp/added" || true)"
  if [ -n "$f_new" ]; then
    echo "::error file=$f::New permission grant(s) committed to $f — move them to untracked local config (AGENTS.md: never commit a permission grant)." >&2
    printf '  %s\n' "$f_new" >&2
  fi
done < "$tmp/head_files"

exit 1
