#!/usr/bin/env bash
#
# Fail if the given head SHA has no accepted-author PR comment carrying
# `Reviewed head: <sha>` under both `# Code quality review` and
# `# Security review verdict`.
#
# If a project migrates its review headers later (a rename, a merge of two
# review skills), add the old header as a second accepted `startswith` arm
# below for as long as an open PR might still carry a pre-rename review, then
# drop it — that is exactly the situation this guard was built to survive.
#
# This is a visibility aid, not a security control: it proves a review
# comment was posted for this exact head, not that the review itself was
# sound (the pr-review skill's reviewer subagents already give that
# independence). A comment matching the marker text is satisfiable by
# anyone who can comment on the PR, which is why the workflow step calling
# this script filters to accepted authors *before* handing comments here —
# this script trusts whatever comments.json contains and does not itself
# check authorship.
#
# Usage: check_review_coverage.sh <head-sha> <comments-json-file>
# comments-json-file: a JSON array of {"body": "..."} objects, pre-filtered
# by the caller to comments from an accepted author.
set -euo pipefail

head_sha="${1:?usage: check_review_coverage.sh <head-sha> <comments-json-file>}"
comments_file="${2:?usage: check_review_coverage.sh <head-sha> <comments-json-file>}"

marker="Reviewed head: ${head_sha}"

quality_found=$(jq --arg marker "$marker" '
  [ .[] | select(.body | startswith("# Code quality review"))
        | select(.body | contains($marker)) ] | length > 0
' "$comments_file")

security_found=$(jq --arg marker "$marker" '
  [ .[] | select(.body | startswith("# Security review verdict"))
        | select(.body | contains($marker)) ] | length > 0
' "$comments_file")

status=0

if [ "$quality_found" != "true" ]; then
  echo "::error::No code-quality review found for head ${head_sha} (looked for an accepted-author comment starting \"# Code quality review\" containing \"${marker}\")." >&2
  status=1
fi

if [ "$security_found" != "true" ]; then
  echo "::error::No security review found for head ${head_sha} (looked for an accepted-author comment starting \"# Security review verdict\" containing \"${marker}\")." >&2
  status=1
fi

if [ "$status" -eq 0 ]; then
  echo "OK: both reviews found for head ${head_sha}."
fi

exit "$status"
