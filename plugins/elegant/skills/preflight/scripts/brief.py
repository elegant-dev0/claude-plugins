#!/usr/bin/env python3
"""Build the brief that every finder and checker starts from, once per review.

Usage (from the repo root):
  brief.py --base SHA --head SHA [--working-tree] [--siblings PATH,PATH] [--out FILE]

It holds what each finder would otherwise look up for itself:
- the functions, types and constants the change touches, with their callers and tests;
- where the changed names, and the env vars, routes and keys in the diff, appear in the sibling
  repos' main branch;
- the REVIEW.md "Never flag" lines whose globs match a changed path;
- the specs and ADRs the change edits, its commits name, or that mention the changed names.

It reads only: git, and the files git shows. No network, no build. It writes the brief to --out
(default: the Preflight state folder in the git common dir) and prints a JSON summary with its path.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profile as prof  # noqa: E402  (sibling repos and generated paths come from the project's profile)

EXCLUDE = [f':(exclude,glob){p}' for p in prof.DEFAULT_GLOBS]  # widened in main() from the profile
TEST = re.compile(r'(^|/)(__tests__|tests?)/|\.(test|spec)\.[cm]?[jt]sx?$')
DOC = re.compile(r'\.mdx?$')
IDENT = r'[A-Za-z_$][\w$]*'
DECLS = [
    re.compile(r'^\s*export\s+(?:default\s+)?(?:async\s+)?function\*?\s+(' + IDENT + ')'),
    re.compile(r'^\s*export\s+(?:declare\s+)?(?:const|let|var|class|type|interface|enum|abstract\s+class)\s+(' + IDENT + ')'),
    re.compile(r'^\s*(?:async\s+)?function\*?\s+(' + IDENT + r')\s*[(<]'),
    re.compile(r'^\s*(?:const|let)\s+(' + IDENT + r')\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|' + IDENT + r')\s*(?::[^=]+)?=>'),
    re.compile(r'^\s*(?:const|let)\s+([A-Z][A-Z0-9_]{2,})\s*[:=]'),
    re.compile(r'(?i)^\s*create\s+(?:or\s+replace\s+)?(?:function|table|view)\s+(?:if\s+not\s+exists\s+)?(?:public\.)?"?([a-z_]\w*)'),
    re.compile(r'^\s*def\s+([A-Za-z_]\w*)\s*\('),
]
ENV = re.compile(r'\b[A-Z][A-Z0-9]*_[A-Z0-9_]*[A-Z0-9]\b')
ROUTE = re.compile(r'''['"`](/(?:api|v\d|mcp)/[^'"`\s?#]*)''')
KEY = re.compile(r'\b([a-z][a-z0-9]*[A-Z][A-Za-z0-9]*)\??\s*:(?!:)')
PKG = re.compile(r'^\s*"(@?[a-z0-9][\w.-]*(?:/[\w.-]+)?)"\s*:\s*"(?:workspace:|npm:|catalog:|[\^~<>=*]|\d)')
MANIFEST_KEYS = {'version', 'node', 'bun', 'npm', 'pnpm', 'yarn'}
STOP = {'default', 'props', 'data', 'error', 'value', 'result', 'state', 'type', 'name', 'index', 'config',
        'options', 'params', 'args', 'children', 'key', 'item', 'items', 'test', 'describe', 'expect',
        'className', 'onClick', 'onChange', 'onSubmit', 'onOpenChange', 'ariaLabel', 'tabIndex'}
CAP_CODE, CAP_TESTS, CAP_DOCS, CAP_SIB, COMMON = 6, 3, 2, 3, 60


def git(*args, cwd=None, ok=(0,)):
    r = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout if r.returncode in ok else ''


def glob_rx(g):
    """A REVIEW.md path glob as a regex: ** spans folders, * and ? stay inside one, {a,b} is either."""
    out, i = '', 0
    while i < len(g):
        if g.startswith('**/', i):
            out, i = out + '(?:.*/)?', i + 3
        elif g.startswith('**', i):
            out, i = out + '.*', i + 2
        elif g[i] == '*':
            out, i = out + '[^/]*', i + 1
        elif g[i] == '?':
            out, i = out + '[^/]', i + 1
        elif g[i] == '{' and g.find('}', i) > i:
            j = g.find('}', i)
            out, i = out + '(?:' + '|'.join(re.escape(x) for x in g[i + 1:j].split(',')) + ')', j + 1
        else:
            out, i = out + re.escape(g[i]), i + 1
    return re.compile('^' + out + '$')


def changed_lines(diff):
    """(file, text, is_context) for each added, removed or hunk-context line of a unified diff."""
    cur = None
    for line in diff.splitlines():
        if line.startswith('+++ '):
            cur = line[6:] if line.startswith('+++ b/') else None
        elif line.startswith('--- ') or cur is None:
            continue
        elif line.startswith('@@'):
            yield cur, line.split('@@', 2)[-1], True
        elif line[:1] in '+-':
            yield cur, line[1:], False


def collect(diff):
    symbols, terms, packages = {}, {}, {}
    for path, text, is_context in changed_lines(diff):
        if TEST.search(path):
            continue  # a test's own helpers and fixtures are not names the change exports
        if path.endswith('package.json'):
            m = PKG.match(text)
            if m and not is_context and m.group(1) not in MANIFEST_KEYS:
                packages.setdefault(m.group(1), set()).add(path)
            continue
        for rx in DECLS:
            m = rx.search(text)
            if m and m.group(1) not in STOP and len(m.group(1)) >= 3:
                symbols.setdefault(m.group(1), set()).add(path)
        if is_context:
            continue
        for rx in (ENV, ROUTE, KEY):
            for m in rx.finditer(text):
                t = m.group(1) if rx.groups else m.group(0)
                if t not in STOP and len(t) >= 4:
                    terms[t] = terms.get(t, 0) + 1
    return symbols, terms, packages


def quoted(pkg):
    """How code, manifests and docs name a package: as a quoted specifier, or a subpath of one."""
    return [f"'{pkg}'", f'"{pkg}"', f"'{pkg}/", f'"{pkg}/', f'`{pkg}`']


def defines(text, name):
    return any((m := rx.search(text)) and m.group(1) == name for rx in DECLS)


def uses(name, tree):
    out = git('grep', '-n', '-I', '-w', '-F', '-e', name, *([tree] if tree else []), '--', '.', *EXCLUDE, ok=(0, 1))
    code, tests, docs = [], [], []
    for line in out.splitlines():
        parts = line.split(':', 3) if tree else [None] + line.split(':', 2)
        if len(parts) < 4:
            continue
        _, path, ln, text = parts
        if defines(text, name):
            continue
        where = tests if TEST.search(path) else docs if DOC.search(path) else code
        where.append(f'{path}:{ln}: {text.strip()[:140]}')
    return code, tests, docs


def package_uses(pkg, tree):
    args = ['grep', '-n', '-I', '-F']
    for q in quoted(pkg):
        args += ['-e', q]
    out = git(*args, *([tree] if tree else []), '--', '.', *EXCLUDE, ok=(0, 1))
    hits = []
    for line in out.splitlines():
        parts = line.split(':', 3) if tree else [None] + line.split(':', 2)
        if len(parts) == 4:
            hits.append((bool(DOC.search(parts[1])), bool(TEST.search(parts[1])), parts[1].startswith('examples/'),
                         f'{parts[1]}:{parts[2]}: {parts[3].strip()[:140]}'))
    return [h[3] for h in sorted(hits, key=lambda h: h[:3])]


def sibling_hits(sib, terms, packages=()):
    ref = 'origin/main' if git('rev-parse', '--verify', '--quiet', 'origin/main', cwd=sib).strip() else 'HEAD'
    when = git('log', '-1', '--format=%cs', ref, cwd=sib).strip()
    out = ''
    if terms:
        args = ['grep', '-n', '-I', '-w', '-F']
        for t in terms:
            args += ['-e', t]
        out = git(*args, ref, '--', '.', *EXCLUDE, cwd=sib, ok=(0, 1))
    if packages:
        args = ['grep', '-n', '-I', '-F']
        for p in packages:
            for q in quoted(p):
                args += ['-e', q]
        out += git(*args, ref, '--', '.', *EXCLUDE, cwd=sib, ok=(0, 1))
    hits = {}
    for line in out.splitlines():
        parts = line.split(':', 3)
        if len(parts) < 4:
            continue
        _, path, ln, text = parts
        for p in packages:
            if any(q in text for q in quoted(p)):
                hits.setdefault(f'{p} (package)', []).append((bool(DOC.search(path)), bool(TEST.search(path)), path.startswith('examples/'),
                                                              f'{path}:{ln}: {text.strip()[:140]}'))
        for t in terms:
            if re.search(r'(?<![\w$])' + re.escape(t) + r'(?![\w$])', text):
                hits.setdefault(t, []).append((bool(DOC.search(path)), bool(TEST.search(path)), path.startswith('examples/'),
                                               f'{path}:{ln}: {text.strip()[:140]}'))
    # Code first, then tests, then docs, and examples after package code: the code is what a change can break.
    return ref, when, {t: [h[3] for h in sorted(v, key=lambda h: h[:3])] for t, v in hits.items()}


def review_lines(paths, base, head):
    text, src = git('show', f'{base}:REVIEW.md'), 'base'
    if not text:
        text, src = git('show', f'{head}:REVIEW.md'), 'head (not at base yet)'
    picked, in_never = [], False
    for line in text.splitlines():
        if line.startswith('## '):
            in_never = line.strip().lower() == '## never flag'
            continue
        if not in_never or not line.startswith('- `'):
            continue
        globs = re.findall(r'`([^`]+)`', line[2:].split(' · ', 1)[0])
        if any(g == '**' or any(glob_rx(g).match(p) for p in paths) for g in globs):
            picked.append(line)
    return src if text else None, picked


def spec_files(paths, commits, names, tree, packages=()):
    listed = git('ls-tree', '-r', '--name-only', tree or 'HEAD', '--', 'specs').splitlines()
    changed = [p for p in paths if p.startswith('specs/') or '/adrs/' in p]
    named = set(re.findall(r'\bspecs/[\w./-]+?\.md\b', commits))
    for n in re.findall(r'(?i)\bspec\s+(\d{1,2})\b', commits):
        named.update(f for f in listed if re.match(rf'specs/0?{int(n)}-', f))
    for n in re.findall(r'\bADR-(\d{3})\b', commits):
        named.update(f for f in listed if re.match(rf'specs/adrs/{n}-', f))
    mentions = {}
    docs = ['--', ':(glob)specs/**', ':(glob)docs/**', ':(glob)**/*.md', ':(glob)**/*.mdx', *EXCLUDE]
    outs = []
    if names:
        args = ['grep', '-c', '-I', '-w', '-F']
        for t in names:
            args += ['-e', t]
        outs.append(git(*args, *([tree] if tree else []), *docs, ok=(0, 1)))
    if packages:  # a package is named in prose as `ai` or 'ai', never as a bare word worth matching
        args = ['grep', '-c', '-I', '-F']
        for p in packages:
            for q in quoted(p):
                args += ['-e', q]
        outs.append(git(*args, *([tree] if tree else []), *docs, ok=(0, 1)))
    for out in outs:
        for line in out.splitlines():
            path, count = line.rsplit(':', 1)
            if tree:
                path = path.split(':', 1)[1]  # drop the "<sha>:" prefix
            if path not in changed:
                mentions[path] = mentions.get(path, 0) + int(count)
    return changed, sorted(named - set(changed)), sorted(mentions.items(), key=lambda kv: -kv[1])[:8]


def main():
    a = sys.argv[1:]
    def opt(name, default=None):
        return a[a.index(name) + 1] if name in a else default
    base, head = opt('--base'), opt('--head')
    if not base or not head:
        raise SystemExit(__doc__)
    working = '--working-tree' in a
    started = time.time()
    root = git('rev-parse', '--show-toplevel').strip()
    match = prof.detect(root)
    global EXCLUDE
    EXCLUDE = [f':(exclude,glob){p}' for p in prof.generated_globs(match)]
    diff = git('diff', '--no-ext-diff', '-U0', base) if working else git('diff', '--no-ext-diff', '-U0', f'{base}...{head}')
    if working:
        for f in git('ls-files', '--others', '--exclude-standard').splitlines():
            try:
                body = open(os.path.join(root, f), errors='replace').read()
            except OSError:
                continue
            diff += f'\n+++ b/{f}\n' + ''.join('+' + l + '\n' for l in body.splitlines())
    numstat = git('diff', '--numstat', base) if working else git('diff', '--numstat', f'{base}...{head}')
    files = [(p, ad, de) for ad, de, p in (l.split('\t', 2) for l in numstat.splitlines() if l.count('\t') >= 2)]
    paths = [p for p, _, _ in files]
    commits = git('log', '--format=%s%n%b', f'{base}..{head}')
    tree = None if working else head
    symbols, terms, packages = collect(diff)

    sibs = opt('--siblings')
    siblings = [s for s in sibs.split(',') if s] if sibs is not None else prof.siblings(root, match)
    folder_names = {r.get('folder', n): n for n, r in ((match.profile or {}).get('repos') or {}).items()}
    # Searched in the other repos and the specs: names with a capital, an underscore or a slash.
    # A plain lowercase word ("times") matches prose everywhere and tells a finder nothing.
    distinct = lambda t: re.search(r'[A-Z_/]', t) is not None
    names = [s for s in symbols if distinct(s)][:40] + [
        t for t, _ in sorted(terms.items(), key=lambda kv: -kv[1]) if t not in symbols and distinct(t)][:40]

    origin = git('remote', 'get-url', 'origin').strip()
    repo = re.sub(r'\.git$', '', origin.rstrip('/').rsplit('/', 1)[-1]) if origin else os.path.basename(root)
    lines = [f'# Review brief: {repo} {base[:8]}...{head[:8]}' + (' plus uncommitted work' if working else ''), '',
             'Built once, before the finders, from git alone. Start from it, and do not repeat its searches.',
             'Callers come from `git grep` at head; other repos from their main branch. Re-read the code itself.', '']
    lines += [f'## Changed files ({len(files)})'] + [f'- {p} (+{ad} -{de})' for p, ad, de in files] + ['']

    lines.append(f'## Changed functions, types and constants ({len(symbols)})')
    for name, where in list(symbols.items())[:40]:
        code, tests, docs = uses(name, tree)
        lines.append(f'### `{name}` (changed in {", ".join(sorted(where))})')
        if len(code) + len(tests) > COMMON:
            lines.append(f'- {len(code)} uses and {len(tests)} test lines: a common name, not listed')
            continue
        for label, items, cap in (('used in', code, CAP_CODE), ('tests', tests, CAP_TESTS), ('docs', docs, CAP_DOCS)):
            if items:
                more = f' (+{len(items) - cap} more)' if len(items) > cap else ''
                lines.append(f'- {label}{more}:')
                lines += [f'  - {x}' for x in items[:cap]]
        if not (code or tests or docs):
            lines.append('- no other uses found')
    lines.append('')

    if packages:
        lines.append(f'## Changed dependencies ({len(packages)})')
        for pkg, where in packages.items():
            uses_ = package_uses(pkg, tree)
            lines.append(f'### `{pkg}` (in {", ".join(sorted(where))})')
            more = f' (+{len(uses_) - CAP_CODE} more)' if len(uses_) > CAP_CODE else ''
            lines += [f'- named in{more}:'] + [f'  - {x}' for x in uses_[:CAP_CODE]] if uses_ else ['- named nowhere else in this repo']
        lines.append('')

    lines.append('## Where the changed names appear in the other repos')
    if not siblings:
        lines.append('- no sibling repos found next to this one')
    elif not names and not packages:
        lines.append('- not searched: the brief found no changed functions, keys or packages to look for. '
                     'Search the other repos yourself for whatever this change touches.')
        siblings = []
    for sib in siblings:
        ref, when, hits = sibling_hits(sib, names, list(packages))
        label = folder_names.get(os.path.basename(sib), os.path.basename(sib))
        lines.append(f'### {label} ({ref}, last commit {when or "unknown"})')
        if not hits:
            lines.append('- none of the changed names')
        for t in sorted(hits, key=lambda t: -len(hits[t])):
            lines.append(f'- `{t}` ({len(hits[t])}):')
            lines += [f'  - {x}' for x in hits[t][:CAP_SIB]]
    lines.append('')

    src, picked = review_lines(paths, base, head)
    lines.append(f'## REVIEW.md lines that apply' + (f' (from {src})' if src else ''))
    lines += picked or ['- no REVIEW.md in this repo' if not src else '- none match the changed paths']
    lines.append('')

    changed, named, mentions = spec_files(paths, commits, names, tree, list(packages))
    lines.append('## Specs and ADRs')
    lines.append('- changed here: ' + (', '.join(changed) or 'none'))
    lines.append('- named in the commits: ' + (', '.join(named) or 'none'))
    lines.append('- mention the changed names: ' + (', '.join(f'{p} ({n})' for p, n in mentions) or 'none'))
    seconds = round(time.time() - started, 1)
    lines += ['', f'_Built in {seconds}s._']

    out = opt('--out')
    if not out:
        common = git('rev-parse', '--path-format=absolute', '--git-common-dir').strip()
        branch = git('symbolic-ref', '--quiet', '--short', 'HEAD').strip()
        key = re.sub(r'[^A-Za-z0-9._-]+', '_', branch or f'detached-{head[:12]}')
        os.makedirs(prof.state_dir(common), exist_ok=True)
        out = os.path.join(prof.state_dir(common), f'{key}-{head[:8]}-brief.md')
    with open(out, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(json.dumps({'brief': out, 'files': len(files), 'symbols': len(symbols), 'packages': len(packages), 'otherRepoNames': len(names),
                      'reviewLines': len(picked), 'specs': len(changed) + len(named) + len(mentions), 'seconds': seconds}))


if __name__ == '__main__':
    main()
