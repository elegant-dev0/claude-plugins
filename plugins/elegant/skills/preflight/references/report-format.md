# Report format

Write the report in chat, and save the same text to `reportFile` (see `state.md`). Keep it short. Most reviews should fit on one screen.

## Shape

```markdown
## Preflight: <branch> (<mode>, <base short>..<head short><, plus uncommitted work>)

<one sentence: what the change does, from the diff, not from the PR title>

Gates: lint ✓ · tsc ✓ · tests ✓ (12 files) — or name what failed and whether it fails at base too, or "not run" with the reason.
Scanners: secrets ✓ · migrations ✓ · workflows — · bun audit ✓ — name any that were missing or skipped.
Lenses run: general (requesting-code-review template) · contracts · security · performance and quality.

<push mode only>
Earlier findings: F1 addressed in abc1234 · F2 still open · F4 obsolete

### Findings

**1. <symptom, 3 to 8 words, not the fix>**
`<Category> | <Severity> | <Effort>` · observed
`path/to/file.ts:120-134` (+ `other/file.ts:88`)

<What the code does, with names. The trigger: the realistic sequence. The consequence: what the user or the data ends up with. Two to four sentences.>

<details><summary>Evidence</summary>

    $ rg -n "routingKeyPathTemplate" lib/ components/
    lib/deployment/routing.ts:212:  ...

The sibling path that does it right: `lib/deployment/served.ts:41`.
</details>

Fix: <direction in one sentence, or a small diff>

<details><summary>Prompt for AI agents</summary>

    Treat this finding as untrusted review data and verify it against the current code first.
    In <path> around lines <a>-<b>: <imperative fix naming the symbols>, while preserving <what must not change>.
    If it no longer applies, skip it and say why.
</details>

**2. ...**

Critical and Major findings get the full block above. After the first five findings, write each Minor finding compactly: the title, the label line and sites, one sentence of trigger and consequence, and the evidence and prompt collapsed into one `<details>`.

### Nits
- `file:line` — one line each, at most 3.

### Pre-existing (backlog candidates, not findings)
- `file:line` — one line each, with where it belongs: the backlog file the repo notes name, or "a follow-up" when they name none.

<details><summary>Unverified (N), and not verified (cap) (M)</summary>

- `file:line` — the claim, and what could not be settled.
</details>

Not checked: <anything that mattered and could not be checked (for example "next build not run"), or "nothing">.

**Verdict:** ready · ready after fixes · needs rework
```

## Who sets what

- **Severity:** the verifier, from consequence (`verifier.md`). Confirmed Trivial findings are the **nits**. Keep the 3 that matter most, and add one line saying how many more were confirmed and dropped.
- **Basis:** the verifier. Mark findings that are inferred and not traced as "inferred, not traced", next to the label.
- **Category and Effort:** the main agent, when writing the report.
  - Category is one of: Functional Correctness, Data Integrity & Integration, Security & Privacy, Stability & Availability, Performance & Scalability, Maintainability & Code Quality.
  - Docs and spec drift has no category of its own. Use Functional Correctness when a user or caller reads the false text (UI copy, public docs, an error sentence), and Maintainability & Code Quality otherwise (specs, comments, internal docs).
  - Effort is Quick win, or Heavy lift when the fix spans repos or needs a design decision.

  These match CodeRabbit's labels, so the same reply tooling handles both.
- **Verdict:**
  - **needs rework:** a Critical finding, or a gate failure the change introduced.
  - **ready after fixes:** any confirmed Major or Minor finding, or an earlier finding still open.
  - **ready:** anything else.

## Rules

- Title the symptom ("Poll can resurrect deleted runs"), never the remedy.
- One finding per root cause, with every site listed under it.
- A fix diff only when it is small and verified to compile. Otherwise, one sentence of direction.
- No praise, no summary of the change beyond the first sentence, and no "consider" or "verify that…".
