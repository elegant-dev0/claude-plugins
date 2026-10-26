#!/usr/bin/env python3
"""PreToolUse hook: hold `gh pr create` in the repos of a gated profile (profile.json "gate": true)
until Preflight has reviewed the commit the PR would propose. Other repos are never held.

Wired by the elegant plugin's hooks/hooks.json as a Bash hook filtered by `"if": "Bash(gh pr create *)"`.
It reads the hook input on stdin and the review's state file,
<git common dir>/preflight/<branch>.json (or the older subcore-review/), which Preflight saves on every run. The command
runs (exit 0) when that file's `lastReviewed` is the commit the PR would propose. Otherwise it is
blocked (exit 2), and stderr tells the session why.

Skip: `PREFLIGHT_SKIP=1 gh pr create ...` (the older SUBCORE_REVIEW_SKIP=1 works too). A session uses it
only when the user asked.
An error inside the gate blocks too, so a broken gate gets noticed; the skip still works then.

Text inside quotes and heredoc bodies is prose, not a command, so it is ignored, except `$( )`
and backticks inside double quotes, which run.

Limits: the command is read best-effort. A `gh pr create` inside `bash -c`, `eval` or a script,
a PR opened through `gh api`, and a `cd` into a shell variable are not followed.
"""
import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profile as prof  # noqa: E402  (which repos are gated comes from the profiles)

START = r'(?:^|[;&|(\n`]|\$\()\s*'
ASSIGN = r'[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|\'[^\']*\'|[^\s;&|]*)\s+'
GH = re.compile(START + r'(?P<env>(?:' + ASSIGN + r')*)(?:\S*/)?gh\s+pr\s+create\b')
CD = re.compile(START + r'cd\s+(?:"([^"]*)"|\'([^\']*)\'|([^\s;&|)]+))')
SKIP = re.compile(r'(?:^|\s)(?:PREFLIGHT_SKIP|SUBCORE_REVIEW_SKIP)=(?:1|"1"|\'1\')\s')
SKIP_HINT = ('Skip the review only if the user asked for that for this PR: rerun the command as '
             '`PREFLIGHT_SKIP=1 gh pr create ...`.')


def mask_literals(cmd):
    """`cmd` with the text of single-quoted strings, plain double-quoted strings and heredoc
    bodies blanked, at the same length, so prose that mentions gh pr create is not a command.
    A double-quoted string holding `$(` or a backtick is kept: that part runs."""
    out, i, n = list(cmd), 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c == '\\':
            i += 2
        elif c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                break
            out[i + 1:j] = ' ' * (j - i - 1)
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n and cmd[j] != '"':
                j += 2 if cmd[j] == '\\' else 1
            if j >= n:
                break
            if '$(' not in cmd[i + 1:j] and '`' not in cmd[i + 1:j]:
                out[i + 1:j] = ' ' * (j - i - 1)
            i = j + 1
        elif cmd.startswith('<<', i) and (h := re.match(r'<<-?\s*([\'"]?)([A-Za-z_]\w*)\1', cmd[i:])):
            body = cmd.find('\n', i)
            if body < 0:
                break
            end = re.compile(r'^\s*' + re.escape(h.group(2)) + r'\s*$', re.M).search(cmd, body + 1)
            stop = end.start() if end else n
            out[body + 1:stop] = [ch if ch == '\n' else ' ' for ch in cmd[body + 1:stop]]
            i = stop
        else:
            i += 1
    return ''.join(out)


def git(root, *args):
    r = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else None


def block(msg):
    print(f'Not opening this PR yet: {msg}', file=sys.stderr)
    sys.exit(2)


def gh_flags(cmd, masked, end):
    """--repo and --head of the gh pr create that ends at `end`, up to the next separator."""
    stop = end + len(re.split(r'[;&|\n]', masked[end:], maxsplit=1)[0])
    rest = cmd[end:stop]
    try:
        toks = shlex.split(rest)
    except ValueError:
        toks = rest.split()
    out = {}
    for i, t in enumerate(toks):
        for name, short, long in (('repo', '-R', '--repo'), ('head', '-H', '--head')):
            if t in (short, long) and i + 1 < len(toks):
                out[name] = toks[i + 1]
            elif t.startswith(long + '='):
                out[name] = t.split('=', 1)[1]
    return out


def check(cmd, masked, m, cwd):
    where = cwd
    for c in CD.finditer(masked[:m.start()]):
        gi = next(i for i in (1, 2, 3) if c.group(i) is not None)
        d = cmd[c.start(gi):c.end(gi)]
        target = os.path.join(where, os.path.expanduser(os.path.expandvars(d)))
        if d != '-' and os.path.isdir(target):
            where = os.path.normpath(target)
    flags = gh_flags(cmd, masked, m.end())

    named = None  # the gated repo the command names
    if 'repo' in flags:
        mm = re.match(r'^(?:https?://github\.com/)?([^/\s]+)/([^/\s]+?)(?:\.git)?/?$', flags['repo'])
        if not mm:
            return
        owners = {(r.get('github') or '').split('/')[0].lower() for p in prof.load_all() if p.get('gate')
                  for r in p.get('repos', {}).values()}
        if re.search(r'[$`]', flags['repo']):
            if re.search(r'[$`]', mm.group(1)) or mm.group(1).lower() in owners:
                block(f'the review gate cannot tell which repo `{flags["repo"]}` is. '
                      'Run gh pr create once per repo, with the repo written out. ' + SKIP_HINT)
            return
        named = prof.by_slug(f'{mm.group(1)}/{mm.group(2)}')
        if not prof.gated(named):
            return  # no profile gates that repo

    root = git(where, 'rev-parse', '--show-toplevel')
    if root is None:
        if named:
            block(f'the review gate found no git checkout at {where}. '
                  f'Run gh pr create from the {named.repo} checkout. ' + SKIP_HINT)
        return  # not a git repo, and no gated repo named
    here = prof.detect(root)
    if named is None:
        if not prof.gated(here):
            return
        named = here
    elif (here.github or '').lower() != (named.github or '').lower():
        block(f'the PR is for {named.repo}, but this checkout ({root}) is {here.repo if here.profile else "not one of its repos"}. '
              f'Run gh pr create from the {named.repo} checkout. ' + SKIP_HINT)

    head = flags.get('head', '')
    branch = head.split(':', 1)[1] if ':' in head else head
    if branch:
        commit = (git(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}^{{commit}}')
                  or git(root, 'rev-parse', '--verify', '--quiet', f'refs/remotes/origin/{branch}^{{commit}}'))
        if not commit:
            block(f'the review gate cannot find branch {branch} in {root}. ' + SKIP_HINT)
    else:
        branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
        commit = git(root, 'rev-parse', 'HEAD')

    # The same name scope.py gives the state file.
    key = re.sub(r'[^A-Za-z0-9._-]+', '_', branch or f'detached-{commit[:12]}')
    common = git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    state_file = prof.state_file(common, key)
    last, problem = None, ''
    if os.path.exists(state_file):
        try:
            with open(state_file) as f:
                last = json.load(f).get('lastReviewed')
        except (OSError, ValueError) as e:
            problem = f'; its state file could not be read ({e})'
    last_full = git(root, 'rev-parse', '--verify', '--quiet', f'{last}^{{commit}}') if last else None
    if last_full == commit:
        return

    if last_full:
        seen = f'it last reviewed {last_full[:7]}'
    elif last:
        seen = f'its last review, {str(last)[:7]}, is not in this repo'
    else:
        seen = 'it has not reviewed this branch' + problem
    block(f'Preflight has not reviewed {named.repo} {branch or "(detached HEAD)"} at {commit[:7]} ({seen}). '
          'Run /elegant:preflight on this branch, then run this command again. ' + SKIP_HINT)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError as e:
        print(f'Preflight gate: could not read the hook input ({e}); the command was not checked.',
              file=sys.stderr)
        sys.exit(1)
    cmd = (data.get('tool_input') or {}).get('command') or ''
    try:
        masked = mask_literals(cmd)
    except Exception:  # unmasked is stricter, never looser
        masked = cmd
    m = GH.search(masked)
    if not m:
        return
    if SKIP.search(cmd[m.start('env'):m.end('env')]):
        print(json.dumps({'systemMessage': 'Preflight gate skipped for this PR (PREFLIGHT_SKIP=1).'}))
        return
    try:
        check(cmd, masked, m, data.get('cwd') or os.getcwd())
    except Exception as e:  # fail closed: a broken gate must not pass PRs silently
        block(f'the review gate itself failed ({type(e).__name__}: {e}). Tell the user. ' + SKIP_HINT)


if __name__ == '__main__':
    main()
