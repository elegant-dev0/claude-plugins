# elegant.dev Claude Code plugins

A plugin marketplace for elegant.dev. It holds one plugin, **elegant**, which brings **Preflight**: a pre-push and pre-merge code review that checks every finding against the code before reporting it.

## Install

In Claude Code:

```
/plugin marketplace add elegant-dev0/claude-plugins
/plugin install elegant@elegant-dev0
```

Or from a terminal: `claude plugin marketplace add elegant-dev0/claude-plugins`, then `claude plugin install elegant@elegant-dev0`. Restart Claude Code afterwards.

To update later, run `claude plugin marketplace update elegant-dev0` and then `claude plugin update elegant@elegant-dev0`.

## What you need on your machine

- Claude Code, `git`, `python3` (standard library only), and `gh` logged in to GitHub.
- `bun`, for the probe checks in JavaScript and TypeScript repos.
- Optional, for stronger scans: `brew install gitleaks actionlint zizmor shellcheck`.
- For a project with a profile: the profile in `~/.claude/preflight/profiles/<name>/`, and the project's repos cloned side by side in one folder, so the review can compare across them. elegant.dev's own profiles are in a private repo; teammates clone it there.

See [plugins/elegant/README.md](plugins/elegant/README.md) for how to use it.
