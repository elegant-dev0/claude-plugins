# Monogram Labs Claude Code plugins

A plugin marketplace for Monogram Labs. It holds one plugin, **elegant**, which brings **Preflight**: a pre-push and pre-merge code review that checks every finding against the code before reporting it.

## Install

In Claude Code:

```
/plugin marketplace add monogram-labs/claude-plugins
/plugin install elegant@monogram-labs
```

Or from a terminal: `claude plugin marketplace add monogram-labs/claude-plugins`, then `claude plugin install elegant@monogram-labs`. Restart Claude Code afterwards.

To update later, run `claude plugin marketplace update monogram-labs` and then `claude plugin update elegant@monogram-labs`.

## What you need on your machine

- Claude Code, `git`, `python3` (standard library only), and `gh` logged in to GitHub.
- `bun`, for the probe checks in JavaScript and TypeScript repos.
- Optional, for stronger scans: `brew install gitleaks actionlint zizmor shellcheck`.
- For a project with a profile: the profile in `~/.claude/preflight/profiles/<name>/`, and the project's repos cloned side by side in one folder, so the review can compare across them. A team keeps its profiles in a private repo of its own and clones it there.

See [plugins/elegant/README.md](plugins/elegant/README.md) for how to use it.
