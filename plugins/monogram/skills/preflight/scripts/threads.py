#!/usr/bin/env python3
"""List, reply to and resolve PR review threads for Preflight.

Usage:
  threads.py list    --repo OWNER/NAME --pr N            # every thread, ours and other reviewers'
  threads.py reply   --repo OWNER/NAME --pr N --thread THREAD_ID --reply TEXT [--dry-run]   # answer, leave open
  threads.py resolve --repo OWNER/NAME --pr N --thread THREAD_ID --reply TEXT [--dry-run]   # answer, then resolve

Our threads carry a hidden marker `<!-- preflight:fp=<fingerprint> -->` in their first comment (older ones
say `subcore-review:fp=`; both count as ours).
`list` prints JSON: id, isResolved, isOutdated, path, line, ours, fingerprint, fixedMark (a comment says
"Addressed in" or "fixed in <sha>"), title, firstCommentId, and
each comment's author, time and body (trimmed). Read-only except `reply` and `resolve` without --dry-run.
Every reply starts with TAG, as everything the skill posts does. Both refuse a thread we did not start.
"""
import json, re, subprocess, sys

TAG = '[✈️ Preflight]'  # starts everything the skill posts
MARK = re.compile(r'<!-- (?:preflight|subcore-review):fp=(.+?) -->')  # a fingerprint holds a path, so take all of it
MARKER = '<!-- preflight:fp={} -->'
FIXED = re.compile(r'addressed in|fixed in [0-9a-f]{7}', re.I)  # our resolve reply, and CodeRabbit's edit of its own comment
QUERY = """
query($owner:String!, $name:String!, $pr:Int!, $after:String) {
  repository(owner:$owner, name:$name) { pullRequest(number:$pr) {
    reviewThreads(first:100, after:$after) {
      pageInfo { hasNextPage endCursor }
      nodes { id isResolved isOutdated path line originalLine
        comments(first:50) { nodes { databaseId author { login } createdAt body } } } } } } }
"""


def title_of(body):
    """A thread's title. CodeRabbit leads with bold labels (severity, category, effort) and a collapsed
    analysis, then puts its title in bold; others start with the title, sometimes after a badge image."""
    body = re.sub(r'<details>.*?</details>|<!--.*?-->', ' ', body or '', flags=re.S)
    body = re.sub(r'<[^>]+>|!\[[^\]]*\]\([^)]*\)', ' ', body)
    for b in re.findall(r'\*\*(.+?)\*\*', body, flags=re.S):
        if len(re.findall(r'[A-Za-z]{2,}', b)) >= 4:  # labels are one to three words
            return re.sub(r'\s+', ' ', b).strip()[:140]
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', re.sub(r'[*`#>|]', ' ', body))
    return re.sub(r'\s+', ' ', re.split(r'(?<=[.!?])\s', text.strip(), maxsplit=1)[0])[:140]


def tagged(text):
    text = text.strip()
    return text if text.startswith(TAG) else f'{TAG} {text}'


def gh(args, input_text=None):
    r = subprocess.run(['gh', *args], capture_output=True, text=True, input=input_text)
    if r.returncode != 0:
        raise SystemExit(f'gh {" ".join(args[:3])} failed: {r.stderr.strip()[:300]}')
    return r.stdout


def list_threads(repo, pr):
    owner, name = repo.split('/')
    threads, after = [], None
    while True:
        args = ['api', 'graphql', '-f', f'query={QUERY}', '-f', f'owner={owner}', '-f', f'name={name}', '-F', f'pr={pr}']
        if after:
            args += ['-f', f'after={after}']
        data = json.loads(gh(args))['data']['repository']['pullRequest']['reviewThreads']
        for t in data['nodes']:
            cs = t['comments']['nodes']
            first = cs[0] if cs else {}
            m = MARK.search(first.get('body') or '')
            threads.append({
                'id': t['id'], 'isResolved': t['isResolved'], 'isOutdated': t['isOutdated'],
                'path': t['path'], 'line': t['line'] or t['originalLine'],
                'ours': bool(m), 'fingerprint': m.group(1) if m else None,
                'fixedMark': any(FIXED.search(c['body'] or '') for c in cs),  # before bodies are trimmed
                'title': title_of(first.get('body')),
                'firstCommentId': first.get('databaseId'),
                'comments': [{'author': (c.get('author') or {}).get('login'), 'at': c['createdAt'],
                              'body': re.sub(r'\s+', ' ', re.sub(r'<!--.*?-->', '', c['body'] or '', flags=re.S))[:600]} for c in cs],
            })
        if not data['pageInfo']['hasNextPage']:
            return threads
        after = data['pageInfo']['endCursor']


def main():
    a = sys.argv[1:]
    cmd = a[0]
    repo = a[a.index('--repo') + 1]; pr = int(a[a.index('--pr') + 1])
    if cmd == 'list':
        print(json.dumps(list_threads(repo, pr), indent=1))
        return
    if cmd in ('reply', 'resolve'):
        tid = a[a.index('--thread') + 1]; reply = tagged(a[a.index('--reply') + 1])
        t = next((x for x in list_threads(repo, pr) if x['id'] == tid), None)
        if not t:
            raise SystemExit(f'no thread {tid} on {repo}#{pr}')
        if not t['ours']:
            raise SystemExit('refusing: this thread was not started by Preflight')
        resolve = cmd == 'resolve'
        if '--dry-run' in a:
            print(json.dumps({'would_reply_to': t['firstCommentId'], 'reply': reply, 'would_resolve': tid if resolve else None}))
            return
        gh(['api', f'repos/{repo}/pulls/{pr}/comments/{t["firstCommentId"]}/replies', '-f', f'body={reply}'])
        if resolve:
            gh(['api', 'graphql', '-f', 'query=mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}', '-f', f'id={tid}'])
        print(json.dumps({'replied': True, 'resolved': tid if resolve else None}))
        return
    raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
