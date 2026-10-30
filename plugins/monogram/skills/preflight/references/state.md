# State and push mode

## The state file

`scope.py` prints the path as `stateFile`. It lives in the git common directory, so it is never committed and is shared by every worktree of the repo. The report goes beside it as `reportFile`. Create the folder with `mkdir -p <stateDir>` before the first write.

```json
{
  "lastReviewed": "<head sha>",
  "base": "<base sha>",
  "scope": "committed | working-tree",
  "reviewedAt": "<ISO time>",
  "startedAt": "<ISO time the review began>",
  "branch": "<branch name>",
  "pr": "<PR number, or null>",
  "mode": "full | push | spec | quick",
  "skillVersion": "<scope.py's skillVersion, copied as is>",
  "finders": ["General", "Contracts", "Security", "Design", "Standards", "Claims"],
  "findings": [
    {
      "id": "F3",
      "sites": ["lib/x.ts:120-134"],
      "anchor": "functionName · `const y = …`",
      "claim": "one sentence",
      "severity": "Major",
      "category": "Functional Correctness",
      "finders": ["Contracts", "Claims"],
      "status": "open | addressed | dismissed | obsolete",
      "statusNote": "addressed in abc1234 | the user's reason | …",
      "rounds": 1,
      "fingerprint": "<repo>:<path>:<anchor symbol>:<short claim slug>",
      "threadId": "<GitHub review thread id once posted, else null>"
    }
  ],
  "refuted": [
    {"claim": "one sentence", "sites": ["lib/x.ts:88"], "finders": ["General"], "reason": "the check's one-line reason"}
  ]
}
```

- Store confirmed findings, nits included. Store each refuted candidate too, one line in `refuted`: it is never posted, and the ledger uses it to tell a miss no finder raised from one a check threw out. Unverified and capped candidates are not stored.
- `finders` on a finding names every finder that proposed it before triage merged them; the run-level `finders` lists the finders that ran. The ledger (SKILL.md, Step 7) scores each finder from these, so leave none out. `fixed` and `declined` are read as `addressed` and `dismissed`.
- **Merge, never overwrite.** On every write, keep every earlier finding and update its status. A full review of a branch with a state file still keeps `dismissed` and `addressed` entries, so they are not raised again.
- Match a new finding to an earlier one by meaning: the same anchor, or the same claim at a nearby site. Titles change between runs; anchors and claims mostly do not.
- Step 6 (a declined finding) rewrites the state file right away with `status: dismissed` and the user's reason.
- When the scope was `working-tree`, `lastReviewed` is still head, but the next run will see the uncommitted files as changed. That is expected.

## Push mode

`scope.py` puts the increment in `increment`: the files whose PR diff changed since `last` (compared by patch-id, so a merge from main or a clean rebase does not count), and the commits the author added (`--no-merges`).

1. **Same as last** (`sameAsLast: true`): set `lastReviewed` to head, report the earlier findings' status, and stop. The PR gate (`scripts/pr_gate.py`) reads `lastReviewed`, so a merge from main that changed nothing still needs this write.
2. **Re-check open findings first.** For each `open` finding, read its anchor at head. Mark it `addressed` (name the commit that fixed it), still `open`, or `obsolete` (the code is gone). This comes first in the report, because it is what the author needs next. When the PR has threads, the GitHub thread is the record: resolve our addressed threads (SKILL.md, Step 6). An author's reply on a thread counts like a decline in chat.
3. **Review the increment.** Run Steps 2-4 of SKILL.md over `increment.files`, sized by their lines. Give each finder the earlier findings. The fix commits deserve the closest look: two thirds of later-round bot findings on Subcore PRs were bugs in the fixes, and they were accepted more often than first-round findings.
4. **Repeat check.** Before reporting, match every new finding against all earlier findings. Drop it if it matches a `dismissed` one, unless the code got worse. Drop it if it matches an `addressed` one, unless the fix was reverted. Increment `rounds` when a finding comes back on the same block.
5. **Cap follow-ups.** When a block reaches `rounds: 3`, list its remaining edge cases as one line for the author to decide, instead of new findings.
6. **Rebased or force-pushed** (`rebasedOrForced: true`): the patch-id comparison still finds the files whose content changed. Review those, and match earlier findings by anchor.
