"""GitHub reads for the public bot repo and writes for homelab. No credentials in errors."""
import base64
import json
import urllib.error
import urllib.request
from engine import PAGE, MARKER, branch_for, require_sha

BOT = 'alchemmist/socrat-bot'
HOME = 'alchemmist/homelab'

class GitHubError(Exception):
    pass

def _request(url, token=None, method='GET', body=None):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'socrat-wiki-openapi',
               'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if body is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise GitHubError(f'GitHub {method} failed (HTTP {exc.code})') from None

class BotRepo:
    def files(self, before, after):
        require_sha(after)
        if before == '0' * 40:
            commit = _request(f'https://api.github.com/repos/{BOT}/commits/{after}')
            if not commit:
                raise GitHubError('Commit not found')
            return commit.get('files') or []
        require_sha(before)
        compared = _request(f'https://api.github.com/repos/{BOT}/compare/{before}...{after}')
        if not compared:
            raise GitHubError('Compare not found')
        if len(compared.get('files') or []) >= 300:
            raise GitHubError('Compare file list truncated')
        return compared.get('files') or []

    def text(self, sha, path):
        require_sha(sha)
        if path not in ('openapi.yaml', 'scripts/render_wiki.py'):
            raise GitHubError('Unexpected bot path')
        item = _request(f'https://api.github.com/repos/{BOT}/contents/{path}?ref={sha}')
        if not item or item.get('encoding') != 'base64':
            raise GitHubError('Bot file missing')
        return base64.b64decode(item['content']).decode()

class Homelab:
    def __init__(self, token):
        self.token = token

    def api(self, method, path, body=None):
        return _request(f'https://api.github.com/repos/{HOME}/{path}', self.token, method, body)

    def read_page(self, ref='main'):
        item = self.api('GET', f'contents/{PAGE}?ref={ref}')
        if item is None:
            return None, None
        if item.get('encoding') != 'base64':
            raise GitHubError('Unexpected page encoding')
        return base64.b64decode(item['content']).decode(), item['sha']

    def propose(self, after, markdown):
        branch = branch_for(after)
        existing = self.api('GET', f'pulls?state=open&head=alchemmist:{branch}&per_page=20') or []
        if existing:
            return {'status': 'existing', 'number': existing[0]['number'], 'url': existing[0]['html_url']}
        current, _ = self.read_page('main')
        if current == markdown:
            return {'status': 'no_change'}
        main = self.api('GET', 'git/ref/heads/main')['object']['sha']
        self.api('POST', 'git/refs', {'ref': 'refs/heads/' + branch, 'sha': main})
        _, blob = self.read_page(branch)
        body = {'message': 'docs: refresh Socrat Bot wiki page from openapi.yaml', 'branch': branch,
                'content': base64.b64encode(markdown.encode()).decode()}
        if blob:
            body['sha'] = blob
        self.api('PUT', 'contents/' + PAGE, body)
        pr = self.api('POST', 'pulls', {
            'title': 'docs: refresh Socrat Bot wiki page',
            'head': branch, 'base': 'main',
            'body': 'Regenerated `wiki/content/platform/socrat-bot.md` from the current socrat-bot OpenAPI spec.\n\n'
                    f'Source commit: https://github.com/{BOT}/commit/{after}\n\n'
                    'Human review required. No auto-merge.\n\n' + MARKER})
        return {'status': 'created', 'number': pr['number'], 'url': pr['html_url']}

    def automation_prs(self, keep):
        found, page = [], 1
        while page <= 5:
            batch = self.api('GET', f'pulls?state=open&per_page=50&page={page}') or []
            if not batch:
                break
            for pr in batch:
                if pr.get('number') == keep:
                    continue
                if MARKER in (pr.get('body') or '') and pr.get('user', {}).get('login') == 'socrat-bot[bot]':
                    found.append({'number': pr['number'], 'title': pr['title'],
                                  'body': (pr.get('body') or '')[:800], 'url': pr['html_url']})
            if len(batch) < 50:
                break
            page += 1
        return found

    def close(self, number, survivor):
        self.api('POST', f'issues/{number}/comments', {
            'body': f'Superseded by #{survivor}. The wiki page is regenerated from the current OpenAPI spec, so this proposal is stale.'})
        self.api('PATCH', f'pulls/{number}', {'state': 'closed'})
