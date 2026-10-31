"""GitHub API boundary. No shell commands and no credentials in logs."""
import base64
import json
import re
import urllib.error
import urllib.request
from engine import REPO, UPDATES, UnsafeInput

class GitHub:
    def __init__(self, token):
        self.token = token

    def api(self, method, path, body=None):
        # All destinations are fixed; model input never controls API paths.
        request = urllib.request.Request('https://api.github.com/repos/' + REPO + '/' + path,
            method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + self.token,
                     'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                     'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'GitHub {method} failed (HTTP {exc.code})') from None

    def compare(self, before, after):
        for sha in (before, after):
            if not re.fullmatch('[a-f0-9]{40}', sha):
                raise UnsafeInput('Full SHA required')
        result = self.api('GET', f'compare/{before}...{after}?per_page=100&page=1')
        if result.get('status') not in ('ahead', 'identical'):
            raise UnsafeInput('Non-forward push requires manual review')
        # Files are returned on page one only; reject ambiguous/truncated compares.
        if len(result.get('files', [])) >= 300:
            raise UnsafeInput('Compare file limit exceeded')
        total = result.get('total_commits', 0)
        if total > 1000:
            raise UnsafeInput('Commit range too large')
        commits = result.get('commits', [])
        page = 2
        while len(commits) < total:
            extra = self.api('GET', f'compare/{before}...{after}?per_page=100&page={page}').get('commits', [])
            if not extra:
                raise UnsafeInput('Incomplete commit pagination')
            commits.extend(extra)
            page += 1
        result['commits'] = commits
        return result

    def read_updates(self, ref):
        f = self.api('GET', f'contents/{UPDATES}?ref={ref}')
        if f.get('encoding') != 'base64':
            raise UnsafeInput('Unexpected GitHub content encoding')
        return base64.b64decode(f['content']).decode(), f['sha']

    def propose(self, after, content, reason, draft=False):
        if not re.fullmatch('[a-f0-9]{40}', after):
            raise UnsafeInput('Full SHA required')
        branch = 'automation/blog-updates-' + after + ('-test' if draft else '')
        # Include closed PRs: closing a proposal is an editorial decision, not a retry.
        existing = self.api('GET', f'pulls?state=all&head=alchemmist:{branch}&per_page=100')
        if existing:
            return {'status': 'existing', 'url': existing[0]['html_url']}
        # Pin proposal to the analyzed commit. A later main change cannot be silently overwritten.
        main = self.api('GET', 'git/ref/heads/main')['object']['sha']
        if main != after:
            raise UnsafeInput('main advanced; reanalysis required')
        original, _ = self.read_updates(after)
        if content == original:
            return {'status': 'no_change'}
        # Ref creation is an atomic idempotency lock: a competing delivery fails closed.
        self.api('POST', 'git/refs', {'ref': 'refs/heads/' + branch, 'sha': after})
        _, file_sha = self.read_updates(branch)
        self.api('PUT', 'contents/' + UPDATES, {
            'message': 'docs: propose reader-facing blog updates', 'branch': branch,
            'sha': file_sha, 'content': base64.b64encode(content.encode()).decode()})
        pr = self.api('POST', 'pulls', {'title': 'docs: add blog Updates entry',
            'head': branch, 'base': 'main', 'draft': draft,
            'body': 'Automatically proposed; human review required. No auto-merge.\n\n'
                    + f'Source commit: https://github.com/{REPO}/commit/{after}\n\n'
                    + reason[:2000]})
        return {'status': 'created', 'url': pr['html_url']}
