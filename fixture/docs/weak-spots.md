# Weak spots

Repo-specific classes of mistake that have recurred. Read by the `build`
skill's self-review and by both reviewer agents. **Written only by the `retro`
skill.** At most 30 entries. An entry that has not fired in two consecutive
retros is removed by the retro that notices — except a `security`-tagged
entry, which is removed only with a stated reason.

Tags: `security` (an access-control, credential, or token defect),
`data-integrity` (a defect that corrupts or loses stored state), `correctness`
(everything else). Only `security` changes the expiry rule above.

The two rows below are fixture data. They exist so that a skill which reads
this file finds a non-empty, well-formed table.

| Class | Tag | What to check | Added | Last fired |
|-------|-----|---------------|-------|------------|
| Gate bypass on a new read path | security | Every path that returns a widget resolves `widgets.demo_enabled` first, including internal helpers and any new list endpoint | demo-foundation | demo-foundation |
| Owner taken from input | correctness | A widget's `owner` comes from the stored record, never from caller-supplied fields on an update | demo-foundation | demo-foundation |
