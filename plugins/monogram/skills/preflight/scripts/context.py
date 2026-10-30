#!/usr/bin/env python3
"""Write the context file that every finder and check in one review reads first.

Usage (from the repo root, after scope.py and brief.py):
  context.py --scope FILE --brief FILE [--siblings PATH,PATH] [--probes DIR] [--pr-note TEXT] [--out FILE]

--scope is scope.py's JSON output saved to a file. The context file holds what every subagent
prompt used to repeat: the scope, this repo's notes, the "Never flag" entries, the finder rules
and return format, and the checking steps. Each prompt then holds only its own task (a lens, or
one candidate), so the main thread writes 20 short prompts instead of 20 long ones. In testing,
writing the long ones took 11 of a review's 36 minutes.

Reads only the skill's references, git, and the files given. Prints a JSON summary with its path.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REFS = os.path.join(os.path.dirname(HERE), 'references')
sys.path.insert(0, HERE)
import profile as prof  # noqa: E402  (repo notes, checks, never-flag entries and siblings come from the profile)
GUIDANCE = ('AGENTS.md', 'CLAUDE.md', 'CONTRIBUTING.md', 'CODING_STANDARDS.md', '.github/CONTRIBUTING.md', 'design.md',
            'GEMINI.md', '.github/copilot-instructions.md', '.cursorrules', '.windsurfrules', '.clinerules')
# Folders other coding tools keep their rules in, with the file endings they read.
GUIDANCE_DIRS = (('.cursor/rules', ('.mdc', '.md')), ('.github/instructions', ('.instructions.md',)),
                 ('.windsurf/rules', ('.md',)), ('.clinerules', ('.md',)))


def guidance(root):
    """The repo's own rules files: the top-level names first, then each rules folder's files in order."""
    found = [g for g in GUIDANCE if os.path.isfile(os.path.join(root, g))]
    for d, ends in GUIDANCE_DIRS:
        full = os.path.join(root, d)
        if os.path.isdir(full):
            found += sorted(os.path.join(d, n) for n in os.listdir(full) if n.endswith(ends))
    return found


def git(*args):
    r = subprocess.run(['git', *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ''


def read(name):
    with open(os.path.join(REFS, name)) as f:
        return f.read()


def sections(text, level):
    """Split markdown into (heading line, body) pairs at one heading level; '' heads the preamble."""
    mark = '#' * level + ' '
    out, head, body = [], '', []
    for line in text.splitlines():
        if line.startswith(mark):
            out.append((head, '\n'.join(body).strip()))
            head, body = line[len(mark):].strip(), []
        else:
            body.append(line)
    out.append((head, '\n'.join(body).strip()))
    return out


def section(text, level, starts):
    return next((b for h, b in sections(text, level) if h.startswith(starts)), '')


def main():
    a = sys.argv[1:]
    def opt(name, default=None):
        return a[a.index(name) + 1] if name in a else default
    scope_path, brief = opt('--scope'), opt('--brief')
    if not scope_path or not brief:
        raise SystemExit(__doc__)
    with open(scope_path) as f:
        s = json.load(f)
    repo, root, base, head = s['repo'], s['repoRoot'], s['base'], s['head']
    match = prof.detect(root)
    probes = opt('--probes', f'/tmp/preflight-probes/{repo}-{head[:8]}')
    sibs = opt('--siblings')
    siblings = [p for p in sibs.split(',') if p] if sibs is not None else prof.siblings(root, match)

    pr = s.get('pr') or {}
    pr_line = (f"#{pr['number']} \"{pr.get('title', '')}\" ({pr.get('url', '')})" if pr.get('number') else
               'none found; the commit messages state the intent')
    lines = [f'# Review context: {repo} {base[:8]}...{head[:8]}', '',
             'Every finder and check in this review reads this file first. It holds what they all share;',
             'your prompt holds only your own task. Use the literal SHAs below in every command: shell',
             'variables do not survive between tool calls.', '',
             '## Scope', '',
             f'- Repo: {root} ({repo}). Mode: {s.get("mode")}. Scope: {s.get("scope")}.',
             f'- Base: {base}', f'- Head: {head}',
             f'- Diff: `{s.get("diffCmd")}`' + (' (uncommitted work included)' if s.get('scope') == 'working-tree' else ''),
             f'- Brief: {brief}',
             f'- Probe folder: {probes} (checks only; finders run no code). Never write in the repo.',
             f'- PR: {pr_line}']
    if opt('--pr-note'):
        lines.append(f'- About the PR: {opt("--pr-note")}')
    untracked = s.get('uncommitted', {}).get('untracked') or []
    if untracked:
        lines.append('- Untracked files, read whole: ' + ', '.join(untracked))
    lines += ['- Commits:'] + [f'  - {c}' for c in s.get('commits') or ['(none)']]
    lines.append('- Changed files (generated ones are not reviewed line by line):')
    for f in s.get('files') or []:
        tags = [t for t in ('generated', 'untracked') if f.get(t)]
        lines.append(f"  - {f['path']} +{f.get('added', 0)} -{f.get('deleted', 0)}" + (f" ({', '.join(tags)})" if tags else ''))
    lines += ['- Sibling repos on disk (read-only; they may sit on another branch, so search their main branch:',
              '  `git -C <path> grep -n <pattern> origin/main -- <paths>`):']
    lines += [f'  - {p}' for p in siblings] or ['  - none found']

    preamble = read('repos.md').split('\n', 1)[-1].strip()  # drop the "# Repos" title
    notes = prof.section(match, 'repos.md', repo)
    if not notes:
        found = guidance(root)
        notes = (f'This repo has no Preflight profile. Its guidance is its own: {", ".join(f"`{g}`" for g in found)}. '
                 'Read them at base; lens L9 walks them.' if found else
                 'This repo has no Preflight profile and no rules file: no AGENTS.md, CLAUDE.md or CONTRIBUTING, '
                 'and no Cursor, Copilot, Gemini, Windsurf or Cline rules.')
    lines += ['', '## Repo notes', '',
              'The guidance that applies is THIS repo\'s, named below. If your context also holds instructions',
              'from another checkout, they do not apply unless they are for this repo.', '',
              preamble, '', notes]
    checks = prof.section(match, 'checks.md', repo, 'All').replace('/tmp/preflight-probes/', probes.rstrip('/') + '/')
    lines += ['', '## Project checks', '', 'Lens L5. Every finder runs these on the diff.', '',
              checks or '- none: this repo has no profile, or its profile adds no checks']

    precedents = read('precedents.md')
    has_review = bool(git('show', f'{base}:REVIEW.md') or git('show', f'{head}:REVIEW.md'))
    lines += ['', '## Never flag', '',
              'A candidate that matches an entry is refuted, unless the code changed in a way the entry does not',
              'cover or one of its exceptions applies. The entries that matter for a candidate are the `**` ones',
              'and those whose glob matches one of its sites.', '']
    if has_review:
        lines += ["This repo's `REVIEW.md` is authoritative for it. Its entries that match the changed paths are in",
                  "the brief, under \"REVIEW.md lines that apply\". Read the file at base for a site outside the diff.", '']
    lines += ['### All repos', '', section(precedents, 2, 'All repos')]
    project = prof.section(match, 'never-flag.md', 'All', *([] if has_review else [repo]))
    if project:
        lines += ['', f"Project entries ({match.profile['name']}" + ('' if has_review else f"; {repo} has no REVIEW.md yet, so its own section follows") + '):', '',
                  project.replace('\n### ', '\n#### ').replace('### ', '#### ', 1)]

    finder = section(read('finder.md'), 2, 'Finder rules')
    verifier = read('verifier.md').split('\n', 1)[-1].strip()  # drop the "# Verifier" title
    lines += ['', '## Finder', '', 'For finders. Checks skip to "Checking".', '', finder.replace('\n### ', '\n#### '),
              '', '## Checking', '', 'For checks.', '', verifier.replace('\n## ', '\n### ')]

    out = opt('--out') or os.path.join(os.path.dirname(os.path.abspath(brief)), f'{repo}-{head[:8]}-context.md')
    with open(out, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(json.dumps({'context': out, 'lines': len(lines), 'siblings': len(siblings), 'reviewMd': has_review}))


if __name__ == '__main__':
    main()
