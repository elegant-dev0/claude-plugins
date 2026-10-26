#!/usr/bin/env python3
"""Tests for pr_gate.py. Builds fake repos in a temp folder; touches no real repo.

Usage: python3 test_pr_gate.py [path/to/pr_gate.py]
"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, 'pr_gate.py')
PY = sys.executable
os.environ['PREFLIGHT_PROFILES'] = os.path.join(os.path.dirname(HERE), 'profiles')  # bundled only: the example gates acme/*
T = os.path.join(tempfile.mkdtemp(prefix='pr-gate-test-'), 'w')


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def g(repo, *args):
    return sh('git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', *args, cwd=repo)


def setup():
    shutil.rmtree(T, ignore_errors=True)
    os.makedirs(T)
    app, other = os.path.join(T, 'app'), os.path.join(T, 'other')
    for repo, origin in ((app, os.path.join(T, 'remotes', 'acme', 'web.git')),
                         (other, 'https://github.com/someone/other.git')):
        os.makedirs(repo)
        g(repo, 'init', '-q', '-b', 'main')
        g(repo, 'remote', 'add', 'origin', origin)
        g(repo, 'commit', '-q', '--allow-empty', '-m', 'one')
    g(app, 'checkout', '-q', '-b', 'claude/test-gate')
    g(app, 'commit', '-q', '--allow-empty', '-m', 'two')
    g(app, 'branch', 'claude/other-branch')
    os.makedirs(os.path.join(T, 'notgit'))
    return app, other


def state(repo, key, last=None, raw=None, folder='subcore-review'):
    d = os.path.join(sh('git', 'rev-parse', '--path-format=absolute', '--git-common-dir', cwd=repo), folder)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f'{key}.json')
    if last is None and raw is None:
        if os.path.exists(p):
            os.remove(p)
        return
    with open(p, 'w') as f:
        f.write(raw if raw is not None else json.dumps({'lastReviewed': last}))


def run(cwd, command, env=None, raw_input=None):
    inp = raw_input if raw_input is not None else json.dumps(
        {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'cwd': cwd, 'tool_input': {'command': command}})
    r = subprocess.run([PY, GATE], input=inp, capture_output=True, text=True, env=env)
    return r.returncode, (r.stderr + r.stdout).strip()


def main():
    app, other = setup()
    notgit = os.path.join(T, 'notgit')
    head = g(app, 'rev-parse', 'HEAD')
    prev = g(app, 'rev-parse', 'HEAD~1')
    key = 'claude_test-gate'
    cases = []

    def case(name, expect_code, cwd, command, contains='', prep=None, env=None, raw_input=None):
        cases.append((name, expect_code, cwd, command, contains, prep, env, raw_input))

    case('not a gh command', 0, app, 'ls -la')
    case('quoted text is not a command', 0, app, 'echo "gh pr create --title x"')
    case('other owner repo', 0, other, 'gh pr create --title x')
    case('not a git repo', 0, notgit, 'gh pr create --title x')
    case('gated repo, no state', 2, app, 'gh pr create --title x', 'has not reviewed this branch',
         prep=lambda: state(app, key))
    case('reviewed at head', 0, app, 'gh pr create --title x', prep=lambda: state(app, key, head))
    case('reviewed at a short sha', 0, app, 'gh pr create --title x', prep=lambda: state(app, key, head[:7]))
    case('reviewed an older commit', 2, app, 'gh pr create --title x', f'last reviewed {prev[:7]}',
         prep=lambda: state(app, key, prev))
    case('corrupt state file', 2, app, 'gh pr create --title x', 'could not be read',
         prep=lambda: state(app, key, raw='{not json'))
    case('unknown last sha', 2, app, 'gh pr create --title x', 'is not in this repo',
         prep=lambda: state(app, key, 'deadbeefdeadbeef'))
    case('skip prefix', 0, app, 'SUBCORE_REVIEW_SKIP=1 gh pr create --title x', 'gate skipped',
         prep=lambda: state(app, key))
    case('skip prefix after push', 0, app, 'git push -u origin x && SUBCORE_REVIEW_SKIP=1 gh pr create', 'gate skipped')
    case('skip on another command does not count', 2, app, 'SUBCORE_REVIEW_SKIP=1 git push && gh pr create',
         'has not reviewed')
    case('cd into a gated repo', 2, other, f'cd {app} && gh pr create --title x', 'has not reviewed')
    case('cd into another repo', 0, app, f'cd {other} && gh pr create --title x')
    case('cd into a missing dir falls back to cwd', 2, app, 'cd "$SOMEWHERE" && gh pr create', 'has not reviewed')
    case('--repo names a gated repo from a foreign checkout', 2, other, 'gh pr create --repo acme/web',
         'Run gh pr create from the acme-web checkout')
    case('--repo with a shell variable', 2, app, 'gh pr create --repo acme/$r --title x', 'cannot tell which repo')
    case('--repo= form, other owner', 0, app, 'gh pr create --repo=someone/else')
    case('--repo another repo of a gated owner', 0, app, 'gh pr create -R acme/not-a-gated-repo')
    case('--head reviewed branch', 0, app, 'gh pr create --head claude/other-branch',
         prep=lambda: state(app, 'claude_other-branch', g(app, 'rev-parse', 'claude/other-branch')))
    case('--head owner:branch form, unreviewed', 2, app, 'gh pr create -H fofiu:claude/other-branch', 'has not reviewed',
         prep=lambda: state(app, 'claude_other-branch'))
    case('--head missing branch', 2, app, 'gh pr create --head nope/nope', 'cannot find branch')
    case('gh by absolute path', 2, app, '/opt/homebrew/bin/gh pr create --title x', 'has not reviewed')
    case('$( ) substitution', 2, app, 'url=$(gh pr create --title x)', 'has not reviewed')
    case('prose in single quotes', 0, app, "printf '%s\\n' 'run `gh pr create` later' >> notes.md")
    case('heredoc body', 0, app, "cat <<'EOF' > notes.md\ngh pr create --title x\nEOF")
    case('double-quoted prose', 0, app, 'git commit -m "fix it; gh pr create next"')
    case('real command after quoted prose', 2, app, "echo 'gh pr create'; gh pr create --title x", 'has not reviewed')
    case('$( ) inside double quotes runs', 2, app, 'echo "$(gh pr create --title x)"', 'has not reviewed')
    case('skip with a quoted value', 0, app, 'SUBCORE_REVIEW_SKIP="1" gh pr create', 'gate skipped')
    case('the new skip name', 0, app, 'PREFLIGHT_SKIP=1 gh pr create --title x', 'gate skipped', prep=lambda: state(app, key))
    case('reviewed at head, new state folder', 0, app, 'gh pr create --title x',
         prep=lambda: (state(app, key), state(app, key, head, folder='preflight')))
    case('an older review in the new folder still blocks', 2, app, 'gh pr create --title x', f'last reviewed {prev[:7]}',
         prep=lambda: state(app, key, prev, folder='preflight'))
    case('a variable in another owner\'s repo passes', 0, app, 'gh pr create --repo someone/$x --title y',
         prep=lambda: state(app, key, folder='preflight'))
    case('quoted cd target', 2, other, f'cd "{app}" && gh pr create', 'has not reviewed')
    case('quoted title with a semicolon', 0, app, 'gh pr create --title "a; b" --head claude/other-branch',
         prep=lambda: state(app, 'claude_other-branch', g(app, 'rev-parse', 'claude/other-branch')))
    case('bad hook input', 1, app, '', 'could not read the hook input', raw_input='not json')
    case('gate error fails closed', 2, app, 'gh pr create --title x', 'gate itself failed',
         env={'PATH': '/nonexistent', 'HOME': os.environ.get('HOME', ''), 'PREFLIGHT_PROFILES': os.environ['PREFLIGHT_PROFILES']})
    case('skip still works when the gate errors', 0, app, 'SUBCORE_REVIEW_SKIP=1 gh pr create', 'gate skipped',
         env={'PATH': '/nonexistent', 'HOME': os.environ.get('HOME', ''), 'PREFLIGHT_PROFILES': os.environ['PREFLIGHT_PROFILES']})

    failed = 0
    for name, code, cwd, command, contains, prep, env, raw_input in cases:
        if prep:
            prep()
        got, out = run(cwd, command, env=env, raw_input=raw_input)
        ok = got == code and contains in out
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: exit {got}" + ('' if ok else f' (want {code} with {contains!r}): {out[:200]}'))

    # Detached HEAD and a worktree share the same state folder (git common dir).
    g(app, 'checkout', '-q', '--detach')
    dkey = f'detached-{head[:12]}'
    state(app, dkey)
    for name, code, prep in (('detached, unreviewed', 2, None), ('detached, reviewed', 0, lambda: state(app, dkey, head))):
        if prep:
            prep()
        got, out = run(app, 'gh pr create')
        ok = got == code
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: exit {got}" + ('' if ok else f': {out[:200]}'))
    g(app, 'checkout', '-q', 'claude/test-gate')
    wt = os.path.join(T, 'wt')
    g(app, 'worktree', 'add', '-q', '-b', 'claude/wt', wt)
    state(app, 'claude_wt', g(wt, 'rev-parse', 'HEAD'))
    got, out = run(wt, 'gh pr create')
    ok = got == 0
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'}  worktree reads the shared state: exit {got}" + ('' if ok else f': {out[:200]}'))

    shutil.rmtree(os.path.dirname(T), ignore_errors=True)
    print(f'\n{len(cases) + 3 - failed} passed, {failed} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
