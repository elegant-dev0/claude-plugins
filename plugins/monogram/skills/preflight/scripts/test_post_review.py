#!/usr/bin/env python3
"""Tests for post_review.py's payload: what lands on GitHub. No network: build_review takes the diff and threads as data.

Usage: python3 test_post_review.py [path/to/post_review.py]
"""
import importlib.util, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, 'post_review.py')


def main():
    sys.path.insert(0, os.path.dirname(PATH))
    spec = importlib.util.spec_from_file_location('post_review', PATH)
    P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)
    hunks = {'lib/a.ts': [set(range(10, 31))]}
    data = {'summary': 'One sentence on the change.\n\nGates: not run.', 'findings': [
        {'fingerprint': 'app:lib/a.ts:f:inside', 'path': 'lib/a.ts', 'line': 20, 'startLine': 18, 'body': '**1. Inside the diff**'},
        {'fingerprint': 'app:lib/b.ts:g:outside', 'path': 'lib/b.ts', 'line': 5, 'body': '**2. Outside the diff**'},
        {'fingerprint': 'app:lib/a.ts:f:open', 'path': 'lib/a.ts', 'line': 12, 'body': '**3. Already open**'},
    ]}
    payload, outside, skipped = P.build_review(data, hunks, {'app:lib/a.ts:f:open'}, 'abc123')
    body, comments = payload['body'], payload['comments']
    first_line = body.split('\n', 1)[0]
    checks = [
        ('never approves or blocks', payload['event'] == 'COMMENT' and payload['commit_id'] == 'abc123'),
        ('the review starts with the tag and counts what is posted', first_line == '[✈️ Preflight] 2 findings, each checked against the code'),
        ('the footer names Preflight and how to decline', 'Preflight, from the monogram plugin' in body and 'decline one with evidence' in body),
        ('a finding in the diff is an inline thread, with its range', len(comments) == 1 and comments[0]['line'] == 20 and comments[0]['start_line'] == 18),
        ('each thread starts with the tag', comments[0]['body'].startswith('[✈️ Preflight] **1. Inside the diff**')),
        ('the hidden marker is the new one', '<!-- preflight:fp=app:lib/a.ts:f:inside -->' in comments[0]['body']),
        ('a finding outside the diff goes in the body, with its marker', len(outside) == 1 and 'Outside the diff (1)' in body
         and '<!-- preflight:fp=app:lib/b.ts:g:outside -->' in body),
        ('a finding with an open thread is skipped', skipped == ['app:lib/a.ts:f:open'] and 'Already open' not in body),
    ]
    named = P.build_review({'summary': '## Preflight: claude/x (full, a..b)\n\nText.', 'findings': []}, {}, set(), 'h')[0]['body']
    checks.append(("the report's heading becomes a plain second line", named.startswith('[✈️ Preflight] 0 findings')
                   and named.split('\n')[2] == 'claude/x (full, a..b)'))
    checks.append(('one finding reads singular', P.build_review({'summary': 'x', 'findings': data['findings'][:1]}, hunks, set(), 'h')[0]
                   ['body'].startswith('[✈️ Preflight] 1 finding,')))

    import io, contextlib, threads as T
    checks.append(('a reply is tagged once', T.tagged('✅ Addressed in abc1234') == '[✈️ Preflight] ✅ Addressed in abc1234'
                   and T.tagged('[✈️ Preflight] Fine.') == '[✈️ Preflight] Fine.'))
    checks.append(('a tagged fix reply still counts as fixed', bool(T.FIXED.search(T.tagged('✅ Addressed in abc1234')))))
    checks.append(('an old subcore-review marker still counts as ours', T.MARK.search('x <!-- subcore-review:fp=a:b:c -->').group(1) == 'a:b:c'
                   and T.MARK.search('<!-- preflight:fp=d:e -->').group(1) == 'd:e'))
    fake = [{'id': 'T1', 'ours': True, 'firstCommentId': 7}, {'id': 'T2', 'ours': False, 'firstCommentId': 8}]
    T.list_threads = lambda repo, pr: fake
    def run(*argv):
        sys.argv = ['threads.py', *argv]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                T.main()
        except SystemExit as e:
            return str(e)
        return buf.getvalue()
    base = ['--repo', 'o/n', '--pr', '1', '--thread']
    r1, r2 = run('reply', *base, 'T1', '--reply', 'The guard is two lines up.', '--dry-run'), run('resolve', *base, 'T1', '--reply', 'x', '--dry-run')
    checks += [
        ('reply leaves the thread open', '"would_resolve": null' in r1 and '[\\u2708\\ufe0f Preflight] The guard' in r1),
        ('resolve resolves it', '"would_resolve": "T1"' in r2),
        ('both refuse a thread we did not start', 'refusing' in run('reply', *base, 'T2', '--reply', 'x', '--dry-run')),
    ]
    failed = 0
    for name, ok in checks:
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f'\n{len(checks) - failed} passed, {failed} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
