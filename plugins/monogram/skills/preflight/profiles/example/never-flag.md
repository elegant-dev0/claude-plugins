# Example: never flag

What reviewers of these repos should not report, under a "## <repo name>" heading, plus "## All repos". A repo's checked-in `REVIEW.md`, if it has one, wins over its section here. Use this shape: `` - `<path glob>` · <what not to flag> · <why> · <date or PR> ``.

## All repos

- `**` · Copy edits in internal docs, unless the text is wrong. · House rule. · 2026-01-01

## acme-web

- `src/legacy/**` · Anything in the legacy folder: it is frozen until its rewrite. · Agreed in planning. · 2026-01-01

## acme-api

- `migrations/**` · Index suggestions for tables under 10,000 rows. · They stay small. · 2026-01-01
