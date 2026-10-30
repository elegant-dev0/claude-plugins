# Never flag

Each entry is something a reviewer should **not** report. A candidate that matches an entry is dropped in triage, or refuted by its verifier, unless the code changed in a way the entry does not cover. Rules to enforce are in `lenses.md` (L5), not here.

The entries come from 274 review-bot findings that authors declined on real PRs, and from the 78 of 519 stored reviewer "learnings" that still hold. Only the ones that apply to any project are here. A project's own go in its profile's `never-flag.md`, or in each repo's `REVIEW.md`. A "Settled conventions" list in a repo's AGENTS.md or CLAUDE.md is also never-flag. A list of defects to catch there is the opposite.

Each repo's checked-in `REVIEW.md` is the shared, authoritative "Never flag" list for that repo. New entries go there (SKILL.md, Step 6), and CodeRabbit reads it too. A profile's `never-flag.md` is the seed and the fallback for its repos whose `REVIEW.md` doesn't exist yet. Use this shape:

```
- `<path glob>` · <what not to flag, one sentence> · <why> · <YYYY-MM-DD, repo#PR>
```

## All repos

- `**` · Problems the change neither adds nor makes reachable: code from a stacked base branch, objects a regenerated dump surfaces, files already over the size cap, behaviour riding on a docs-only change. These are backlog notes, not findings. **Exceptions:** a pre-existing security or data-loss problem still gets one line in the report, marked as pre-existing. A doc the change edits that now contradicts itself is this change's finding, even when the stale sentence predates it: in testing, the author fixed one such contradiction this rule had dropped. · 9% of declines.
- `**` · Requests to hand-edit generated, vendored, copied, applied or published files. Re-point a real problem at its source instead. · 24 declines.
- `**` · A choice recorded at base in a comment, spec, ADR, design.md or AGENTS.md, re-raised without new evidence. Security defaults are the exception: one Minor line that cites the default. · 36 declines. Two "documented defaults" later turned out to be worth fixing.
- `**` · Claims about language, library or platform behaviour that cite no evidence from the installed version: its source, its docs or a run. A finding that cites one stands; one that needs a run to settle is reported as unverified, not dropped. · Wrong examples: JS `$` without the `m` flag, `CONCURRENTLY` inside `supabase db push`, Hono error headers, fetch dropping `Authorization` on a cross-origin redirect.
- `**` · "Missing", "unguarded" or "duplicated" before searching (this repo, and the siblings for docs), or after reading only a few lines around the hunk. · 32 declines, including one false Critical.
- `**` · Parsing or hardening past the stated limit of a scanner, a test or a detection script, for shapes projects don't really ship (block comments, invalid SemVer suffixes). Asking for a sharper limit is fine; more cases need red CI or a real bug. **This does not cover a limit that excludes a shape the project supports or documents** (a workspace root, an installed version outside the required range, a value from an exported env). That limit is itself the finding. · 9 declines.
- `**` · A race, lock or input with no real code path that produces it, or a scaling issue with no realistic data size. · Example: a scaling worry about a 47-row table.
- `**` · Version pins and release placeholders, when the PR states the release order (read its merge conditions, or the commit message when there is no PR body). Also types for a migration not yet applied. **Exception:** a placeholder that nothing stops from shipping. Then the finding is the missing guard, a test or build check that fails while the placeholder remains, not the placeholder's value.
- `**` · Escaping values that an installed package controls before printing them in CI (versions, paths): a package that can plant them can already print any workflow command itself. · 2026-10-23.
- `**` · Latency work off the hot path: CLIs, CI scripts and eval harnesses stay sequential on purpose, and provider calls are never parallelized without a limit. · 5 declines.
- `**` · Wording, Markdown lint and metadata, unless a linter that actually runs enforces it or the text is wrong. Where a prompt or template is compiled or hashed byte for byte, whitespace there is content. · 5 declines.
