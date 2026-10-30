# Repos

A profile's repos sit side by side in one folder, and `profile.py` finds the siblings next to this checkout. `scope.py` identifies the repo and its profile from `git remote get-url origin`. A repo with no profile has no siblings.

Other sessions may use these checkouts, so a sibling may be on a feature branch with uncommitted edits. Never switch its branch. Read a sibling's main branch instead: `git -C <path> fetch origin main --quiet` (offline, skip the fetch and say its main may be stale), then `git -C <path> grep -n <pattern> origin/main -- <paths>` or `git -C <path> show origin/main:<file>`. When the PR names a paired branch in a sibling, read that branch the same way.

A worktree without its own `bun install` silently resolves the parent checkout's `node_modules`, which may be a different version. Before trusting a gate there, check that `node_modules` exists in the worktree. Otherwise run `bun install` first, or list the gate under "Not checked".
