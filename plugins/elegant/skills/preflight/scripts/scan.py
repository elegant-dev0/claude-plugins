#!/usr/bin/env python3
"""Deterministic checks for a Preflight review. Prints JSON hits for the verifiers to confirm.

Usage: scan.py --base SHA --head SHA [--working-tree] [--online]

Runs real scanners when installed (gitleaks, actionlint, zizmor, shellcheck, squawk) and
built-in checks otherwise. Every hit is a candidate, not a finding: Step 4 verifies it.
Read-only. --online allows `bun audit` (it contacts the npm advisory API).
"""
import json, os, re, shutil, subprocess, sys

SECRET_PATTERNS = [
    ('aws-access-key', r'\bAKIA[0-9A-Z]{16}\b'),
    ('github-token', r'\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b'),
    ('slack-token', r'\bxox[abprs]-[A-Za-z0-9-]{10,}\b'),
    ('stripe-live-key', r'\b[rs]k_live_[A-Za-z0-9]{20,}\b'),
    ('anthropic-key', r'\bsk-ant-[A-Za-z0-9_-]{20,}\b'),
    ('openai-key', r'\bsk-(proj-)?[A-Za-z0-9]{32,}\b'),
    ('google-api-key', r'\bAIza[0-9A-Za-z_-]{35}\b'),
    ('twilio-api-key', r'\bSK[0-9a-f]{32}\b'),
    ('private-key', r'-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----'),
    ('supabase-service-jwt', r'\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b'),
    ('assigned-secret', r'(?i)\b(password|passwd|secret|api_?key|auth_?token)\s*[:=]\s*["\'][^"\'\s]{12,}["\']'),
]
SKIP_SECRET = re.compile(r'(^|/)(bun\.lockb?|package-lock\.json|pnpm-lock\.yaml)$|\.snap$')


def sh(cmd, cwd=None, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, '', str(e)


def added_lines(base, head, working_tree, path):
    rng = [base] if working_tree else [f'{base}...{head}']
    _, out, _ = sh(['git', 'diff', '-U0', *rng, '--', path])
    lines, n = [], 0
    for l in out.splitlines():
        m = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', l)
        if m:
            n = int(m.group(1)); continue
        if l.startswith('+') and not l.startswith('+++'):
            lines.append((n, l[1:])); n += 1
    return lines


def main():
    a = sys.argv[1:]
    base = a[a.index('--base') + 1]; head = a[a.index('--head') + 1]
    wt = '--working-tree' in a; online = '--online' in a
    _, root, _ = sh(['git', 'rev-parse', '--show-toplevel']); root = root.strip(); os.chdir(root)
    rng = [base] if wt else [f'{base}...{head}']
    _, names, _ = sh(['git', 'diff', '--name-status', *rng])
    changed = {}
    for l in names.splitlines():
        parts = l.split('\t')
        changed[parts[-1]] = parts[0][0]
    if wt:
        _, untracked, _ = sh(['git', 'ls-files', '--others', '--exclude-standard'])
        for u in untracked.splitlines():
            changed.setdefault(u, 'A')
    hits, tools = [], {}

    def hit(tool, rule, path, line, msg, severity='Minor'):
        hits.append({'tool': tool, 'rule': rule, 'file': path, 'line': line, 'message': msg, 'severity': severity})

    files = [p for p, s in changed.items() if s != 'D' and os.path.isfile(p)]

    # Secrets: a real scanner if present, else the built-in patterns on added lines only.
    if shutil.which('gitleaks'):
        tools['gitleaks'] = 'ran'
        code, out, _ = sh(['gitleaks', 'git', '--no-banner', '--report-format', 'json', '--report-path', '/dev/stdout',
                           '--log-opts', f'{base}..{head}', '.'], timeout=300)
        try:
            for f in json.loads(out or '[]'):
                hit('gitleaks', f.get('RuleID'), f.get('File'), f.get('StartLine'), 'possible secret (gitleaks)', 'Critical')
        except ValueError:
            pass
    else:
        tools['gitleaks'] = 'missing: built-in patterns used'
    for p in files:
        if SKIP_SECRET.search(p):
            continue
        for n, text in added_lines(base, head, wt, p) if not changed[p] == 'A' or not wt else [(i + 1, t) for i, t in enumerate(open(p, errors='ignore').read().splitlines())]:
            for rule, pat in SECRET_PATTERNS:
                m = re.search(pat, text)
                if m and not re.search(r'(?i)example|placeholder|dummy|fake|xxxx|test_|<[^>]+>|\$\{|process\.env', text):
                    val = m.group(0)
                    hit('secrets', rule, p, n, f'possible secret: {val[:6]}… (masked)', 'Critical')

    # Migrations (Supabase): RLS, grants, definer hygiene, edits to applied files, paired regeneration.
    migs = [p for p in changed if re.search(r'supabase/migrations/.*\.sql$', p)]
    for p in migs:
        if changed[p] == 'M':
            hit('migrations', 'applied-migration-edited', p, 1, 'an existing migration was edited; once applied, a fix must be a new migration', 'Major')
        if not os.path.isfile(p):
            continue
        # A new migration is checked whole; an edited one only on the lines the change added.
        sql = open(p, errors='ignore').read() if changed[p] == 'A' else '\n'.join(t for _, t in added_lines(base, head, wt, p))
        low = sql.lower()
        for m in re.finditer(r'create\s+table\s+(?:if\s+not\s+exists\s+)?([\w."]+)', low):
            t = m.group(1).replace('"', '').split('.')[-1]
            ln = low[:m.start()].count('\n') + 1
            if not re.search(rf'alter\s+table\s+[\w."]*{re.escape(t)}"?\s+enable\s+row\s+level\s+security', low):
                hit('migrations', 'table-without-rls', p, ln, f'table {t} is created without ENABLE ROW LEVEL SECURITY in this migration', 'Major')
            if not re.search(rf'revoke\s+[\w\s,]+\s+on\s+(table\s+)?[\w."]*{re.escape(t)}"?\s+from\s+[\w\s,]*anon', low):
                hit('migrations', 'table-not-revoked-from-anon', p, ln, f'new table {t}: Supabase grants ALL to anon by default; only an explicit REVOKE narrows it', 'Minor')
        for m in re.finditer(r'create\s+(?:or\s+replace\s+)?function\s+([\w."]+)\s*\((.*?)\$\$', low, re.S):
            body_start = m.start(); name = m.group(1).replace('"', '').split('.')[-1]
            header = low[body_start:body_start + 1500]
            if 'security definer' in header:
                ln = low[:body_start].count('\n') + 1
                if 'set search_path' not in header:
                    hit('migrations', 'definer-without-search-path', p, ln, f'SECURITY DEFINER function {name} does not pin search_path', 'Major')
                if not re.search(rf'revoke\s+execute\s+on\s+function\s+[\w."]*{re.escape(name)}', low):
                    hit('migrations', 'definer-execute-not-revoked', p, ln, f'SECURITY DEFINER function {name}: new public functions are RPC-callable; REVOKE EXECUTE … FROM PUBLIC, anon, authenticated', 'Major')
        for m in re.finditer(r'create\s+(unique\s+)?index\s+concurrently', low):
            hit('migrations', 'concurrently-in-transaction', p, low[:m.start()].count('\n') + 1, 'supabase db push runs each file in a transaction, which refuses CONCURRENTLY', 'Major')
    if migs and os.path.exists('supabase/prod-schema.sql') and 'supabase/prod-schema.sql' not in changed:
        hit('migrations', 'schema-dump-not-regenerated', migs[0], 1, 'a migration changed but supabase/prod-schema.sql did not (bun run db:schema after it is applied)', 'Minor')
    if migs and os.path.exists('lib/types/database.types.ts') and 'lib/types/database.types.ts' not in changed:
        hit('migrations', 'types-maybe-not-regenerated', migs[0], 1, 'a migration changed but lib/types/database.types.ts did not: check whether it changes anything db:types emits (tables, columns, views, function signatures, enums)', 'Trivial')
    if shutil.which('squawk') and migs:
        tools['squawk'] = 'ran'
        _, out, _ = sh(['squawk', '--assume-in-transaction', *[m for m in migs if os.path.isfile(m)]])
        for l in out.splitlines()[:40]:
            mm = re.match(r'(.+?):(\d+):\d+: (\w+): (.+)', l)
            if mm:
                hit('squawk', mm.group(3), mm.group(1), int(mm.group(2)), mm.group(4))
    elif migs:
        tools['squawk'] = 'missing: built-in migration checks used'

    # GitHub Actions workflows.
    wfs = [p for p in files if re.search(r'^\.github/workflows/.*\.ya?ml$', p)]
    for p in wfs:
        for n, text in added_lines(base, head, wt, p):
            if 'pull_request_target' in text:
                hit('workflows', 'pull-request-target', p, n, 'pull_request_target runs with secrets on untrusted PR code', 'Major')
            um = re.search(r'uses:\s*([\w.-]+/[\w./-]+)@([\w.-]+)', text)
            if um and not re.fullmatch(r'[0-9a-f]{40}', um.group(2)) and not um.group(1).startswith('./'):
                hit('workflows', 'action-not-pinned', p, n, f'{um.group(1)}@{um.group(2)} is not pinned to a commit SHA', 'Trivial')
            if re.search(r'\$\{\{\s*github\.(event\.(pull_request|issue|comment|review|head_commit)|head_ref)', text):
                hit('workflows', 'expression-injection', p, n, 'an attacker-controlled github context value is interpolated; pass it through env: instead', 'Major')
            if re.search(r'echo\s+.*\$\{\{\s*secrets\.', text):
                hit('workflows', 'secret-echoed', p, n, 'a secret is echoed into the log', 'Major')
    for tool in ('actionlint', 'zizmor'):
        if wfs and shutil.which(tool):
            tools[tool] = 'ran'
            _, out, _ = sh([tool, *wfs])
            for l in out.splitlines()[:30]:
                mm = re.match(r'(.+?):(\d+):\d+: (.+)', l)
                if mm:
                    hit(tool, tool, mm.group(1), int(mm.group(2)), mm.group(3))
        elif wfs:
            tools[tool] = 'missing'

    # Shell scripts.
    shs = [p for p in files if p.endswith('.sh')]
    if shs and shutil.which('shellcheck'):
        tools['shellcheck'] = 'ran'
        _, out, _ = sh(['shellcheck', '-f', 'gcc', *shs])
        for l in out.splitlines()[:30]:
            mm = re.match(r'(.+?):(\d+):\d+: (\w+): (.+)', l)
            if mm and mm.group(3) in ('error', 'warning'):
                hit('shellcheck', mm.group(3), mm.group(1), int(mm.group(2)), mm.group(4))
    elif shs:
        tools['shellcheck'] = 'missing'

    # Dependencies.
    pkgs = [p for p in files if p.endswith('package.json')]
    for p in pkgs:
        for n, text in added_lines(base, head, wt, p):
            for dm in re.finditer(r'"([@\w./-]+)":\s*"([^"]+)"', text):
                if dm.group(1) in ('version', 'name', 'main', 'types', 'module', 'description', 'license', 'type', 'homepage', 'url'):
                    continue
                v = dm.group(2)
                if v in ('*', 'latest') or v.startswith(('git+', 'git:', 'http', 'file:', 'github:')):
                    hit('deps', 'unpinned-or-remote-dependency', p, n, f'{dm.group(1)}: "{v}"', 'Minor')
    lock_changed = any(re.search(r'(^|/)(bun\.lockb?|package\.json)$', p) for p in changed)
    if lock_changed and online:
        code, out, err = sh(['bun', 'audit', '--json', '--audit-level=moderate'], timeout=180)
        tools['bun audit'] = 'ran' if code in (0, 1) else f'failed: {(err or out)[:120]}'
        try:
            data = json.loads(out or '{}')
            for pkg, advs in (data.items() if isinstance(data, dict) else []):
                for adv in advs if isinstance(advs, list) else []:
                    hit('bun audit', adv.get('severity', 'advisory'), 'bun.lock', 1, f"{pkg}: {adv.get('title', '')} ({adv.get('url', '')})",
                        'Major' if adv.get('severity') in ('high', 'critical') else 'Minor')
        except ValueError:
            pass
    elif lock_changed:
        tools['bun audit'] = 'skipped: offline'

    print(json.dumps({'tools': tools, 'hits': hits, 'checkedFiles': len(files)}, indent=1))


if __name__ == '__main__':
    main()
