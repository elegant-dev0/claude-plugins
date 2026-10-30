#!/usr/bin/env python3
"""Tests for context.py. Builds a fake repo in a temp folder; touches no real repo.

Usage: python3 test_context.py [path/to/context.py]
"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ['PREFLIGHT_PROFILES'] = os.path.join(os.path.dirname(HERE), 'profiles')  # bundled only
CONTEXT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, 'context.py')


def g(repo, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', *args],
                          cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def write(repo, path, text):
    os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
    with open(os.path.join(repo, path), 'w') as f:
        f.write(text)


def run(repo, T, name, review_md, origin='https://github.com/acme/api.git', guidance=()):
    os.makedirs(repo)
    g(repo, 'init', '-q', '-b', 'main')
    g(repo, 'remote', 'add', 'origin', origin)
    for path in guidance:
        write(repo, path, '# Rules\n')
    with open(os.path.join(repo, 'a.ts'), 'w') as f:
        f.write('export const a = 1\n')
    if review_md:
        with open(os.path.join(repo, 'REVIEW.md'), 'w') as f:
            f.write('# Review rules\n\n## Never flag\n\n- `**` · Local rule. · 2026-10-24\n')
    g(repo, 'add', '-A'); g(repo, 'commit', '-q', '-m', 'base')
    base = g(repo, 'rev-parse', 'HEAD')
    with open(os.path.join(repo, 'a.ts'), 'w') as f:
        f.write('export const a = 2\n')
    g(repo, 'commit', '-q', '-am', 'Change a')
    head = g(repo, 'rev-parse', 'HEAD')
    scope = {'repo': 'acme-api', 'repoRoot': repo, 'base': base, 'head': head, 'mode': 'full', 'scope': 'committed',
             'diffCmd': f'git diff {base}...{head}', 'pr': None, 'uncommitted': {'modified': [], 'untracked': ['new.ts']},
             'commits': ['abc1234 Change a'], 'files': [{'path': 'a.ts', 'added': 1, 'deleted': 1, 'generated': False},
                                                       {'path': 'bun.lock', 'added': 3, 'deleted': 0, 'generated': True}]}
    sp = os.path.join(T, f'{name}-scope.json')
    with open(sp, 'w') as f:
        json.dump(scope, f)
    out = os.path.join(T, f'{name}-context.md')
    r = subprocess.run([sys.executable, CONTEXT, '--scope', sp, '--brief', '/x/brief.md', '--siblings', '/s/app,/s/api',
                        '--pr-note', 'Kit 0.38.0', '--out', out], cwd=repo, capture_output=True, text=True)
    text = open(out).read() if os.path.exists(out) else ''
    return r, text, head


def main():
    T = tempfile.mkdtemp(prefix='context-test-')
    r, text, head = run(os.path.join(T, 'kit'), T, 'plain', review_md=False)
    r2, text2, _ = run(os.path.join(T, 'kit2'), T, 'reviewmd', review_md=True)
    r3, text3, _ = run(os.path.join(T, 'other'), T, 'other', review_md=False, origin='git@github.com:acme/widgets.git', guidance=('AGENTS.md',))
    r4, text4, _ = run(os.path.join(T, 'cursor'), T, 'cursor', review_md=False, origin='git@github.com:acme/tools.git',
                       guidance=('.cursor/rules/db.mdc', '.cursor/rules/app.mdc', '.cursor/rules/notes.txt',
                                 '.github/copilot-instructions.md', '.clinerules/style.md'))
    r5, text5, _ = run(os.path.join(T, 'bare'), T, 'bare', review_md=False, origin='git@github.com:acme/bare.git')
    part = lambda t, title: t.split(f'\n## {title}\n', 1)[-1].split('\n## ', 1)[0] if f'\n## {title}\n' in t else ''
    scope, notes, never, finder, checking = (part(text, x) for x in ('Scope', 'Repo notes', 'Never flag', 'Finder', 'Checking'))
    pchecks = part(text, 'Project checks')
    checks = [
        ('script ran and printed its path', r.returncode == 0 and json.loads(r.stdout or '{}').get('context', '').endswith('plain-context.md')),
        ('scope: literal head SHA', head in scope),
        ('scope: brief path and default probe folder', '/x/brief.md' in scope and f'/tmp/preflight-probes/acme-api-{head[:8]}' in scope),
        ('scope: generated file marked', 'bun.lock +3 -0 (generated)' in scope),
        ('scope: untracked file listed', 'new.ts' in scope),
        ('scope: PR note and siblings', 'Kit 0.38.0' in scope and '/s/app' in scope and '/s/api' in scope),
        ("notes: this repo's section of repos.md", 'api-server' in notes and 'Mirrors' in notes),
        ("notes: no other repo's section", 'React web app' not in notes),
        ('never flag: the all-repos entries', 'Requests to hand-edit generated' in never),
        ("project checks: this repo's and the profile's all-repos", 'openapi/acme.yaml' in pchecks and 'error code added' in pchecks
         and 'client.ts' not in pchecks),
        ('never flag: the profile entries are named', 'Project entries (example' in never),
        ("project checks use this review's probe folder", f'/tmp/preflight-probes/acme-api-{head[:8]}/' in pchecks),
        ('never flag: repo entries when there is no REVIEW.md', 'no REVIEW.md yet' in never and 'Index suggestions' in never),
        ('never flag: with REVIEW.md, repo entries come from the brief', 'no REVIEW.md yet' not in part(text2, 'Never flag')
         and 'in\nthe brief' in part(text2, 'Never flag')),
        ('finder: the rules and the return format', '**Budget.**' in finder and '- id: <lens>-<n>' in finder),
        ('no profile: notes name the repo\'s own guidance', r3.returncode == 0 and 'no Preflight profile' in part(text3, 'Repo notes')
         and '`AGENTS.md`' in part(text3, 'Repo notes')),
        ('no profile: no project checks, no project entries', '- none' in part(text3, 'Project checks')
         and 'Project entries' not in part(text3, 'Never flag') and 'Requests to hand-edit generated' in part(text3, 'Never flag')),
        ('no profile: no siblings guessed', '/s/app' in part(text3, 'Scope')),
        ("no profile: other tools' rules files count, in order", r4.returncode == 0 and
         '`.github/copilot-instructions.md`, `.cursor/rules/app.mdc`, `.cursor/rules/db.mdc`, `.clinerules/style.md`'
         in part(text4, 'Repo notes') and 'notes.txt' not in text4),
        ('no profile and no rules file: says so', r5.returncode == 0 and 'no rules file' in part(text5, 'Repo notes')
         and 'Cursor' in part(text5, 'Repo notes')),
        ('finder: not the prompt template', 'Prompt template' not in finder and 'You are the <name> finder' not in text),
        ('checking: the verifier steps and return', '### Steps' in checking and 'verdict: confirmed | refuted' in checking),
    ]
    failed = 0
    for name, ok in checks:
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print(r.stderr[-800:], r2.stderr[-800:])
    shutil.rmtree(T, ignore_errors=True)
    print(f'\n{len(checks) - failed} passed, {failed} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
