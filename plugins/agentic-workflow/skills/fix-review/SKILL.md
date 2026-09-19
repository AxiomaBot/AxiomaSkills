---
description: Address both PR reviews — self-fetches the quality report and the security verdict for the current head — fix every blocking issue with a sibling sweep, and file or escalate every security-relevant finding even on an otherwise-clean head
argument-hint: "[optional: paste a review report — omit to self-fetch both from the PR]"
---

# Address the PR reviews

**Tier:** fix-review (floor sonnet, recommended opus — disagreeing with a
reviewer on evidence needs judgment). Stop if this session is below the floor;
never switch the session down.

**This skill is the only owner of a security-relevant finding on a PR.** It
runs on a blocking verdict, and equally on a clean head that carries a
security-relevant non-blocking observation or a `## Needs broader manual
review` item — that case is why a clean head is not always a stop, and
nothing else in the workflow drains it (there is no harvest step downstream
of the build).

One pass addresses **both** reviews, because they pull against each other: a
quality finding that asks you to relax a token lifetime, widen a window or
drop a cap is the next security FAIL. Fix them together and find the change
that satisfies both — cap an event-bound link at `min(event_time, 24h)` rather
than dropping the cap. When they genuinely cannot be reconciled, security
wins (it guards what can be released); say so and name the tradeoff.

<review>
$ARGUMENTS
</review>

## Getting the reviews

**You need both halves every time.** Work out which the block above contains
by its H1 — `# Code quality review` and `# Security review verdict` — and
fetch whichever is missing. A paste of one report is the normal case and must
never suppress fetching the other: a FAIL on the half nobody read would merge
behind a green `review-coverage`, which only proves a comment exists.

1. Resolve the open PR for the current branch and its current head SHA.
   **Fail closed:** if you can't resolve exactly one open PR, or the GitHub
   read fails, stop and ask for the missing half as a paste — never proceed
   on one review.
2. Take the most recent comment carrying each H1 — this skill and the
   `review-coverage` guard must agree on what counts as a posted review for a
   head, so if a project ever renames a header, update both together.
3. **Anchor on the SHA, not the timestamp.** Each comment's `Reviewed head:`
   line must equal the current head exactly — a comment reviewing an older
   head can post after a newer push and look current. If either review is
   missing for this head, stop and say so: run the `pr-review` skill first. A
   pasted report is exempt from the SHA check only if you can see it is for
   this head; if you can't tell, treat it as missing.

## Ground rules

- **Blocking issues are fixed now** — a quality "Blocking issues" entry or a
  security FAIL. Never defer one. If one needs a product decision or an ops
  action (rotating a credential, a production env var), stop and say exactly
  what is needed rather than parking it.
- **Fix fully — sweep for siblings, don't patch the cited line.** After fixing
  the spot, grep for every other instance of the same root cause and fix those
  in this pass: every other positional `INSERT ... SELECT *`, every other
  route missing the same guard, every other secret that defaults to a known
  value. The test of a fix is that the next head doesn't surface its sibling.
- **Sweep sibling state, not just sibling call sites.** When the fix changes a
  *rule* about persistent state (when a flag is set, when something counts as
  "sent" or "done"), list every other column, table or cache that exists for
  the same underlying reason and re-check the rule against each one now.
- **Patch once, then redesign.** If this is the second-plus blocking round in
  the same subsystem, the point-fixes are what keep producing the next issue:
  model that subsystem's states and transitions as a whole and fix against all
  of it. Scale it to the blast radius — for a dev-only script or code with a
  declared short shelf life, fix the cited issue and say why you are not
  redesigning. Blast radius governs the *size* of the remediation only, never
  whether a finding gets fixed.
- **A single process is not single-threaded.** Async handlers interleave, a
  scheduler thread runs alongside them, and thread-pool workers run in
  parallel — so check-then-write races and double sends between two requests,
  or a request and a scheduler tick, are **real** and need a DB-level claim or
  unique constraint. Only a finding that genuinely requires multiple
  processes or replicas is a deployment assumption, and only after you have
  confirmed the app runs single-instance. Never a licence for an auth bypass,
  token or secret exposure, injection, or a weakened expiry.
- **You may disagree — with evidence.** Both reviewers see only the compact
  diff context; that blindness buys their independence and is also why some
  findings are wrong. You have the whole codebase: cite the file:line, the
  guard that already exists, or the covering test, and make no change. The bar
  is evidence, not convenience.
- **Prefer telling the user over an awkward workaround.** For `.env`, a
  credential rotation or a deploy setting, state the file and the value.
- **A committed secret or data file is removed from the repo, not just
  gitignored — and you always say whether it ever reached a public branch**,
  since rotating the credential or warning the people affected is the user's
  call and only they can make it.
- **Never soften a security fix to preserve a dev workflow.** Fix it and
  update this project's own docs to document the new requirement instead.

## Steps

1. **Parse** both reports, and sort what they raise into **drained** and
   **not drained** — that distinction, not "nothing blocking", is what makes
   a head a stop.

   A finding is **drained** once it is fixed on this PR (any head); or — a
   **non-blocking** finding only — an existing `docs/deferred.md` entry
   already covers it; or — a `## Needs broader manual review` item — it has
   been verified or escalated in this PR's thread. Draining only ever happens
   once and never comes undone. The reviewers are fresh each round and see
   the whole diff, so they will restate a drained finding on every later
   head; that is expected and means nothing is left to do.

   **A blocking issue or a security FAIL is drained only by being fixed.** An
   entry covering it does not count and never has: blocking issues are fixed
   now, never deferred, and a pass that read an old entry as permission to
   stop would be exactly the deferral that rule forbids.

   Run the rest of this pass when either report carries a **not-drained**
   blocking issue, security FAIL, `## Needs broader manual review` item, or
   security-relevant non-blocking finding (step 4 defines the class) —
   whichever review raised it. When everything is drained or nothing of that
   kind is present, this head stops: report which findings were already
   drained and where, and change nothing. A stop is a stop, not an invitation
   to act on the remaining non-blocking findings — and **never push only to
   re-record something already drained**, which is how a round turns into a
   loop that ends at the orchestrator's escalation guard.
2. **Triage** each blocking issue: read the cited code and state **valid → fix**
   or **disagree → justify** before changing anything.
3. **Fix** each valid one with its sweep. Add the regression test that would
   have caught it — required for a security fix, expected for a data or
   correctness fix. Shared/core services are sacred: run the full suite after
   touching them.
4. **Non-blocking findings.** Fix one only if it is cheap and clearly correct,
   or if it is part of fixing a blocking issue; otherwise leave it in the PR
   thread — this pass files nothing else, and nothing else drains the thread.
   **One carve-out, by the finding and not by its author:** anything
   security-relevant you do not fix — an auth or authorization gap, a
   credential or token exposure, injection, a weakened expiry, a missing
   bypass test for one of those — is appended to `docs/deferred.md` in this
   push, whether the security review or the quality review raised it, so it
   never lives only in a thread. **File it once.** Search the whole file for
   an entry covering the same gap first, **by substance and not by tag** — an
   earlier round of this PR, or another PR entirely, may have filed it under
   a tag you would not think to match. One already there means the finding is
   drained: add nothing, and say in the report which entry covers it.
5. **Security "Needs broader manual review".** Verify each from the codebase
   and report what you found, or escalate it as an explicit step the user must
   complete **before merging**. Never merge past an unresolved one. Verifying
   or escalating one drains it: post the result to the PR thread so the next
   round can see it was answered, and answer it once.
6. **Verify**: run this project's lint, format and test commands
   (`CLAUDE.md` → Commands). Not done until they pass.
7. **Report** each blocking issue as fixed (what, where, swept siblings),
   disagreed (with evidence), or needing a manual step; what you filed to
   `docs/deferred.md`; lint and test results. Do not commit unless asked.
