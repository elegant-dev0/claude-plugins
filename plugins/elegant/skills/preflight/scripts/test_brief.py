#!/usr/bin/env python3
"""Tests for brief.py. Builds fake repos in a temp folder; touches no real repo.

Usage: python3 test_brief.py [path/to/brief.py]
"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BRIEF = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, 'brief.py')


def g(repo, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', *args],
                          cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def write(repo, files):
    for path, body in files.items():
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as f:
            f.write(body)


def repo(path, files, msg='base'):
    os.makedirs(path)
    g(path, 'init', '-q', '-b', 'main')
    write(path, files)
    g(path, 'add', '-A')
    g(path, 'commit', '-q', '-m', msg)
    return g(path, 'rev-parse', 'HEAD')


def main():
    T = tempfile.mkdtemp(prefix='brief-test-')
    app, kit, api = (os.path.join(T, n) for n in ('app', 'kit', 'api'))
    base = repo(app, {
        'lib/limits.ts': 'export const MAX_IDLE_MINUTES = 1440\nexport function clampIdle(minutes: number): number {\n'
                         '  return Math.min(minutes, MAX_IDLE_MINUTES)\n}\n',
        'lib/use.ts': "import { clampIdle } from './limits'\nexport const shown = clampIdle(30)\n",
        '__tests__/limits.test.ts': "import { clampIdle } from '../lib/limits'\n"
                                    "test('clamps', () => expect(clampIdle(5000)).toBe(1440))\n",
        'components/ui/button.tsx': 'export const Button = 1\n',
        'specs/23-idle.md': 'The deployment reports `maxMinutes`, and the console clamps with clampIdle.\n',
        'specs/05-other.md': 'Unrelated.\n',
        'docs/adrs/005-pin.md': 'Pin `ai` exactly.\n',
        'specs/adrs/015-thing.md': 'An ADR.\n',
        'package.json': '{"dependencies": {\n  "ai": "7.0.107"\n}}\n',
        'lib/model.ts': "import { generateText } from 'ai'\n",
        'REVIEW.md': '# Review rules\n\n## Never flag\n\n'
                     '- `**` · Everything rule. · 2026-10-23\n'
                     '- `lib/**` · Lib rule. · 2026-10-23\n'
                     '- `**/*.{ts,tsx}` · TS rule. · 2026-10-23\n'
                     '- `components/ui/**` · Vendored rule. · 2026-10-23\n'
                     '- `docs/**`, `specs/**` · Docs rule. · 2026-10-23\n',
    })
    write(app, {'lib/limits.ts': 'export const MAX_IDLE_MINUTES = 10080\nexport function clampIdle(minutes: number): number {\n'
                                 '  return Math.max(1, Math.min(minutes, MAX_IDLE_MINUTES))\n}\n'
                                 'export const describe = { maxMinutes: MAX_IDLE_MINUTES }\n'
                                 'const ttl = process.env.SMS_SESSION_TIMEOUT_MINUTES\n',
                'package.json': '{"peerDependencies": {\n  "ai": "^7.0.107"\n}}\n'})
    g(app, 'commit', '-q', '-am', 'Raise the cap (spec 23)\n\nSee ADR-015.')
    head = g(app, 'rev-parse', 'HEAD')
    repo(kit, {'src/env.ts': 'export const smsTimeout = Number(process.env.SMS_SESSION_TIMEOUT_MINUTES)\n',
               'src/describe.ts': 'export const sessionIdle = { maxMinutes: 1440 }\n',
               'package.json': '{"dependencies": {"ai": "^7.0.1"}}\n'})
    g(kit, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    write(kit, {'src/describe.ts': 'export const sessionIdle = {}\n'})  # local work past main: must not hide main's line
    g(kit, 'commit', '-q', '-am', 'local only')
    repo(api, {'src/routes.ts': 'export const nothingShared = 1\n'})

    out = os.path.join(T, 'brief.md')
    r = subprocess.run([sys.executable, BRIEF, '--base', base, '--head', head, '--siblings', f'{kit},{api}', '--out', out],
                       cwd=app, capture_output=True, text=True)
    summary = json.loads(r.stdout) if r.returncode == 0 else {}
    text = open(out).read() if os.path.exists(out) else ''
    sections = {s.split('\n', 1)[0]: s for s in text.split('\n## ')}
    def section(title):
        return next((v for k, v in sections.items() if k.startswith(title)), '')
    funcs, others, review, specs, deps = (section(t) for t in ('Changed functions', 'Where the changed names', 'REVIEW.md lines', 'Specs', 'Changed dependencies'))
    clamp = funcs.split('### `clampIdle`', 1)[-1].split('###', 1)[0] if '### `clampIdle`' in funcs else ''
    kit_part = others.split('### kit', 1)[-1].split('###', 1)[0]
    api_part = others.split('### api', 1)[-1].split('###', 1)[0]

    checks = [
        ('script ran and printed its summary', r.returncode == 0 and summary.get('brief') == out),
        ('clampIdle is a changed function', bool(clamp)),
        ('its caller is listed', 'lib/use.ts:2' in clamp),
        ('its test is listed under tests', 'tests' in clamp and '__tests__/limits.test.ts:' in clamp),
        ('its own definition is not listed as a use', 'lib/limits.ts:2' not in clamp),
        ('the changed constant is listed', '### `MAX_IDLE_MINUTES`' in funcs),
        ('kit: the env var is found', '`SMS_SESSION_TIMEOUT_MINUTES`' in kit_part and 'src/env.ts:1' in kit_part),
        ("kit: main's maxMinutes is found despite local work", '`maxMinutes`' in kit_part and 'src/describe.ts:1' in kit_part),
        ('kit: searched on origin/main', 'origin/main' in others.split('### kit', 1)[-1][:40]),
        ('api: says nothing matched', 'none of the changed names' in api_part),
        ('REVIEW.md: the ** rule applies', 'Everything rule' in review),
        ('REVIEW.md: the lib/** rule applies', 'Lib rule' in review),
        ('REVIEW.md: the brace glob applies', 'TS rule' in review),
        ('REVIEW.md: the vendored rule does not', 'Vendored rule' not in review),
        ('REVIEW.md: the docs rule does not', 'Docs rule' not in review),
        ('specs: named by number in the commits', 'specs/23-idle.md' in specs.split('named in the commits:', 1)[-1].split('\n', 1)[0]),
        ('specs: the ADR named in the commits', 'specs/adrs/015-thing.md' in specs),
        ('specs: mentions the changed names', 'specs/23-idle.md (' in specs.split('mention the changed names:', 1)[-1]),
        ('specs: an unrelated spec is left out', 'specs/05-other.md' not in specs),
        ('deps: the changed package is listed', '### `ai`' in deps),
        ('deps: its importer is listed', 'lib/model.ts:1' in deps),
        ('specs: an ADR naming the changed package', 'docs/adrs/005-pin.md (' in specs),
        ('deps: found in the other repo', '`ai (package)`' in kit_part and 'package.json:1' in kit_part),
    ]

    # Uncommitted work: a modified file and an untracked one are part of the brief.
    write(app, {'lib/use.ts': "import { clampIdle } from './limits'\nexport function freshThing() { return clampIdle(1) }\n",
                'lib/new.ts': 'export const brandNewConst = 1\n'})
    out2 = os.path.join(T, 'brief2.md')
    r2 = subprocess.run([sys.executable, BRIEF, '--base', base, '--head', head, '--working-tree', '--siblings', '', '--out', out2],
                        cwd=app, capture_output=True, text=True)
    text2 = open(out2).read() if os.path.exists(out2) else ''
    checks += [
        ('working tree: a modified file counts', r2.returncode == 0 and '### `freshThing`' in text2),
        ('working tree: an untracked file counts', '### `brandNewConst`' in text2),
        ('no siblings: says so', 'no sibling repos found' in text2),
    ]

    # Nothing to look for (an empty diff): it says it did not search, rather than "none found".
    out3 = os.path.join(T, 'brief3.md')
    subprocess.run([sys.executable, BRIEF, '--base', head, '--head', head, '--siblings', kit, '--out', out3], cwd=app, capture_output=True, text=True)
    text3 = open(out3).read() if os.path.exists(out3) else ''
    checks += [('nothing to search: says it did not search', 'not searched' in text3 and 'none of the changed names' not in text3)]

    failed = 0
    for name, ok in checks:
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if failed and r.stderr:
        print(r.stderr[-800:])
    shutil.rmtree(T, ignore_errors=True)
    print(f'\n{len(checks) - failed} passed, {failed} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
