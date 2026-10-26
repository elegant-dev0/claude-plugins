#!/usr/bin/env python3
"""Pin the scope of a Preflight review and print it as JSON.

Usage: scope.py [--mode auto|full|push|spec] [--base REF] [--offline] [--commits-only] [FILE ...]

Prints literal SHAs, the files to review (generated files marked), the change size,
the state file path, and, when an earlier review exists, the increment since it.
Read-only, except `git fetch` of the base branch (skipped with --offline).
"""
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profile as prof  # noqa: E402  (generated paths, signals and repo names come from the project's profile)


def git(*args, check=True, strip=True):
    r = subprocess.run(['git', *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f'git {" ".join(args)} failed: {r.stderr.strip()}')
    if r.returncode != 0:
        return None
    return r.stdout.strip() if strip else r.stdout


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def patch_id(diff_text):
    if not diff_text:
        return None
    r = subprocess.run(['git', 'patch-id', '--stable'], input=diff_text, capture_output=True, text=True)
    return r.stdout.split()[0] if r.stdout.strip() else None


def numstat(range_args):
    out = git('diff', '--numstat', *range_args) or ''
    files = []
    for line in out.splitlines():
        a, d, path = line.split('\t', 2)
        if ' => ' in path:  # rename: keep the new path
            path = re.sub(r'\{[^{}]* => ([^{}]*)\}', r'\1', path).replace('//', '/')
            path = path.split(' => ')[-1]
        files.append({'path': path, 'added': int(a) if a.isdigit() else 0, 'deleted': int(d) if d.isdigit() else 0})
    return files


def main():
    argv = sys.argv[1:]
    mode = 'auto'
    base_ref = None
    offline = '--offline' in argv
    commits_only = '--commits-only' in argv
    named = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--mode':
            mode = argv[i + 1]; i += 2; continue
        if a == '--base':
            base_ref = argv[i + 1]; i += 2; continue
        if a in ('--offline', '--commits-only'):
            i += 1; continue
        named.append(a); i += 1

    root = git('rev-parse', '--show-toplevel')
    os.chdir(root)
    match = prof.detect(root)
    repo = match.repo
    head = git('rev-parse', 'HEAD')
    branch = git('symbolic-ref', '--quiet', '--short', 'HEAD', check=False)

    pr = None
    if not offline and branch:
        out = run(['gh', 'pr', 'view', '--json', 'number,title,baseRefName,url,isDraft'])
        if out:
            pr = json.loads(out)
    if base_ref is None:
        base_branch = (pr or {}).get('baseRefName') or 'main'
        if not offline:
            run(['git', 'fetch', 'origin', base_branch, '--quiet'], timeout=60)
        base_ref = f'origin/{base_branch}' if git('rev-parse', '--verify', '--quiet', f'origin/{base_branch}', check=False) else base_branch
    base = git('merge-base', base_ref, head)

    status = git('status', '--porcelain', '--untracked-files=all', strip=False) or ''
    modified = [l[3:] for l in status.splitlines() if len(l) > 3 and not l.startswith('??')]
    untracked = [l[3:] for l in status.splitlines() if l.startswith('?? ')]
    working_tree = bool(modified or untracked) and not commits_only

    gen = prof.generated_regexes(match, root)
    if working_tree:
        files = numstat([base])
        diff_cmd = f'git diff {base}'
    else:
        files = numstat([f'{base}...{head}'])
        diff_cmd = f'git diff {base}...{head}'
    for f in files:
        f['generated'] = any(p.search(f['path']) for p in gen)
    for u in untracked:
        if u.endswith('/'):
            continue
        try:
            n = sum(1 for _ in open(u, errors='ignore'))
        except OSError:
            n = 0
        files.append({'path': u, 'added': n, 'deleted': 0, 'generated': any(p.search(u) for p in gen), 'untracked': True})
    if named:
        keep = set(named)
        files = [f for f in files if f['path'] in keep] + [
            {'path': p, 'added': 0, 'deleted': 0, 'generated': False, 'named': True}
            for p in named if p not in {f['path'] for f in files}]
    lines = sum(f['added'] + f['deleted'] for f in files if not f['generated'])
    code_only = {'security', 'data', 'performance', 'client'}
    not_code = re.compile(r'(\.mdx?$|__tests__/|\.test\.|\.spec\.|(^|/)test/|fixtures?/)')
    signals = {k: [f['path'] for f in files if not f['generated'] and re.search(p, f['path'], re.I)
                   and not (k in code_only and not_code.search(f['path']))] for k, p in prof.signals(match).items()}
    signals = {k: v for k, v in signals.items() if v}
    size = 'small' if lines <= 150 else 'medium' if lines <= 800 else 'large'

    common = git('rev-parse', '--path-format=absolute', '--git-common-dir')
    state_dir = prof.state_dir(common)
    key = re.sub(r'[^A-Za-z0-9._-]+', '_', branch or f'detached-{head[:12]}')
    state_file = os.path.join(state_dir, f'{key}.json')  # always written here; an older one is still read
    state = None
    if os.path.exists(prof.state_file(common, key)):
        try:
            state = json.load(open(prof.state_file(common, key)))
        except (OSError, ValueError):
            state = None

    increment = None
    if state and state.get('lastReviewed'):
        last, last_base = state['lastReviewed'], state.get('base') or base
        known = git('cat-file', '-e', f'{last}^{{commit}}', check=False) is not None
        if known:
            ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', last, head]).returncode == 0
            changed = []
            for f in files:
                if f.get('untracked'):
                    changed.append(f['path']); continue
                old = git('diff', f'{last_base}...{last}', '--', f['path'], check=False)
                new = git('diff', base, '--', f['path'], check=False) if working_tree else git('diff', f'{base}...{head}', '--', f['path'], check=False)
                if patch_id(old) != patch_id(new):
                    changed.append(f['path'])
            commits = (git('log', '--no-merges', '--format=%h %s', f'{last}..{head}', check=False) or '').splitlines() if ancestor else []
            increment = {'last': last, 'lastBase': last_base, 'rebasedOrForced': not ancestor,
                         'files': changed, 'commits': commits, 'sameAsLast': not changed}
        else:
            increment = {'last': last, 'lastBase': last_base, 'rebasedOrForced': True, 'files': [f['path'] for f in files],
                         'commits': [], 'sameAsLast': False, 'note': 'last reviewed commit no longer exists locally'}

    if mode == 'auto':
        spec_like = files and all(re.match(r'^specs/|/adrs/|\.mdx?$', f['path']) for f in files if not f['generated'])
        mode = 'push' if increment else ('spec' if spec_like else 'full')

    print(json.dumps({
        'repo': repo, 'github': match.github, 'profile': (match.profile or {}).get('name'), 'repoRoot': root, 'branch': branch, 'head': head, 'baseRef': base_ref, 'base': base,
        'pr': pr, 'mode': mode, 'scope': 'working-tree' if working_tree else 'committed', 'diffCmd': diff_cmd,
        'uncommitted': {'modified': modified, 'untracked': untracked},
        'size': {'lines': lines, 'class': size}, 'signals': signals, 'files': files,
        'commits': (git('log', '--format=%h %s', f'{base}..{head}', check=False) or '').splitlines(),
        'stateFile': state_file, 'stateDir': state_dir, 'reportFile': os.path.join(state_dir, f'{key}-{head[:8]}.md'),
        'state': state, 'increment': increment,
    }, indent=1))


if __name__ == '__main__':
    main()
