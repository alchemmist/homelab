import argparse
from http.cookies import SimpleCookie
import json
import time
import urllib.error
import urllib.parse
import urllib.request


parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:18081')
args = parser.parse_args()
base = args.url.rstrip('/')
if urllib.parse.urlsplit(base).hostname not in ('127.0.0.1', 'localhost'):
    raise SystemExit('Runtime smoke tests require a local disposable instance')


def request(path, payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, headers=headers or {})
    try:
        response = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read().decode()


deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    try:
        status, _, _ = request('/healthz')
        if status == 200:
            break
    except OSError:
        pass
    time.sleep(0.5)
else:
    raise SystemExit('Live renderer did not become ready')

assert request('/api/editor/session')[0] == 403
headers = {'X-Socrat-Editor-Key': 'test', 'X-Socrat-WG-Peer': '10.250.0.2'}
status, response_headers, body = request('/api/editor/session', headers=headers)
assert status == 200, (status, body)
cookies = SimpleCookie(response_headers['Set-Cookie'])
headers.update({
    'Cookie': 'wiki_editor_session=' + cookies['wiki_editor_session'].value,
    'X-CSRF-Token': json.loads(body)['csrf_token'],
    'Origin': 'https://wiki.alchemmist.xyz',
    'Content-Type': 'application/json',
})
pages = []
for index, path in enumerate(('_index.md', 'start/edit-wiki.md')):
    status, _, body = request('/api/editor/pages?path=' + urllib.parse.quote(path), headers=headers)
    assert status == 200, (status, body)
    page = json.loads(body)
    page['body'] += '\n\nLive runtime smoke marker ' + str(index) + '\n'
    pages.append(page)
status, _, body = request('/api/editor/tree', headers=headers)
assert status == 200, (status, body)
operations = [
    {'type': 'folder', 'parent': '', 'slug': 'runtime-smoke', 'title': 'Runtime smoke'},
    {'type': 'move', 'source': 'start/edit-wiki.md', 'target_parent': 'runtime-smoke', 'before': None},
]
status, _, body = request('/api/editor/batch', {'pages': pages, 'operations': operations, 'tree_revision': json.loads(body)['revision']}, headers)
assert status == 200, (status, body)
assert json.loads(body)['pages'][1]['path'] == 'runtime-smoke/edit-wiki.md'
for index, (path, url) in enumerate((('_index.md', '/site/'), ('runtime-smoke/edit-wiki.md', '/site/runtime-smoke/edit-wiki/'))):
    marker = 'Live runtime smoke marker ' + str(index)
    status, _, html = request(url)
    assert status == 200 and marker in html, (status, url)
    status, _, source = request('/api/editor/pages?path=' + urllib.parse.quote(path), headers=headers)
    assert status == 200 and marker in json.loads(source)['body'], (status, path)
assert request('/api/editor/pages?path=_index.md')[0] == 403
assert request('/site/')[1].get('Cache-Control') == 'no-store'
status, _, body = request('/api/editor/tree', headers=headers)
assert status == 200, (status, body)
status, _, body = request('/api/editor/batch', {'pages': [], 'operations': [{'type': 'delete', 'source': 'runtime-smoke'}], 'tree_revision': json.loads(body)['revision']}, headers)
assert status == 200, (status, body)
assert request('/site/runtime-smoke/edit-wiki/')[0] == 404
assert request('/api/editor/pages?path=runtime-smoke/edit-wiki.md', headers=headers)[0] == 404
assert 'Live runtime smoke marker 0' in request('/site/')[2]
print('Real Hugo runtime: private API, atomic edit/move/delete publication and immediate HTML reload passed')
