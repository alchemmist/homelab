import hmac
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
import urllib.request

from fastapi import FastAPI, HTTPException, Request, Response
from markdown_it import MarkdownIt
from ruamel.yaml import YAML

ORIGIN = os.getenv('PUBLIC_ORIGIN', 'https://wiki.alchemmist.xyz').rstrip('/')
REPO = os.getenv('GIT_REPOSITORY', '')
WORK = Path(os.getenv('WORK_DIR', '/data/repository'))
BRANCH = os.getenv('GIT_BRANCH', 'main')
GATEWAY_TOKEN = os.getenv('EDITOR_GATEWAY_TOKEN', '')
PREFIX = 'wiki/content'
LOCK = threading.RLock()
SESSIONS = {}
SESSION_LOCK = threading.Lock()
MAX_BODY = 262144
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(RuntimeError)
async def unavailable(request, error):
    return Response(content='Repository operation unavailable; retry shortly', status_code=503)


def git(*args, cwd=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    key = os.getenv('GIT_SSH_KEY')
    if key:
        import shlex
        hosts = os.environ['GIT_KNOWN_HOSTS']
        env['GIT_SSH_COMMAND'] = 'ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -i ' + shlex.quote(key) + ' -o UserKnownHostsFile=' + shlex.quote(hosts)
    try:
        result = subprocess.run(['git', *args], cwd=cwd or WORK, env=env, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('Git operation timed out') from error
    if result.returncode:
        raise RuntimeError('Git operation failed: ' + args[0])
    return result.stdout.strip()


def sync():
    if not (WORK / '.git').exists():
        WORK.parent.mkdir(parents=True, exist_ok=True)
        git('clone', '--branch', BRANCH, '--single-branch', '--', REPO, str(WORK), cwd=WORK.parent)
    git('fetch', 'origin', BRANCH)
    git('reset', '--hard', 'origin/' + BRANCH)


def checked_path(value, section=False):
    if not isinstance(value, str) or '\\' in value or '\x00' in value:
        raise HTTPException(400, 'Invalid content path')
    parts = value.split('/')
    if value == '' and section:
        return WORK / PREFIX
    if any(p in ('', '.', '..') or not re.fullmatch(r'[A-Za-z0-9_.-]+', p) for p in parts):
        raise HTTPException(400, 'Invalid content path')
    if not section and not value.endswith('.md'):
        raise HTTPException(400, 'Only Markdown pages are supported')
    root = WORK / PREFIX
    for node in [WORK / 'wiki', root, *[root.joinpath(*parts[:i]) for i in range(1, len(parts) + 1)]]:
        if node.is_symlink():
            raise HTTPException(400, 'Symbolic links are not supported')
    return root / value


def parse(text):
    if not text.startswith('---\n'):
        raise HTTPException(422, 'Only YAML front matter is supported')
    marker = text.find('\n---', 4)
    if marker < 0:
        raise HTTPException(422, 'Invalid front matter')
    tail = marker + 4
    if tail < len(text) and text[tail] != '\n':
        raise HTTPException(422, 'Invalid front matter delimiter')
    yaml = YAML()
    yaml.preserve_quotes = True
    data = yaml.load(text[4:marker]) or {}
    if not isinstance(data, dict):
        raise HTTPException(422, 'Invalid front matter')
    return data, text[tail:].lstrip('\n')


def page_url(path):
    path = path.removesuffix('.md')
    if path.endswith('_index'):
        path = path[:-6]
    elif path.endswith('/index'):
        path = path[:-5]
    return ORIGIN + '/' + path.strip('/') + ('/' if path.strip('/') else '')


def read_page(path):
    target = checked_path(path)
    if not target.is_file():
        raise HTTPException(404, 'Page not found')
    raw = target.read_bytes()
    try:
        data, body = parse(raw.decode('utf-8'))
    except UnicodeError:
        raise HTTPException(422, 'Page must be UTF-8')
    revision = git('hash-object', '--', str(target))
    return {'path': path, 'title': str(data.get('title', '')), 'body': body, 'revision': revision}


def fields(data):
    title, body = data.get('title'), data.get('body')
    if not isinstance(title, str) or not title.strip() or len(title) > 300 or '\n' in title:
        raise HTTPException(422, 'Title must contain 1–300 characters on one line')
    if not isinstance(body, str) or len(body.encode('utf-8')) > MAX_BODY or '\x00' in body:
        raise HTTPException(422, 'Markdown body must be at most 256 KiB')
    return title.strip(), body


def save(data, create=False):
    title, body = fields(data)
    with LOCK:
        sync()
        if create:
            section, slug = data.get('section', ''), data.get('slug', '')
            parent = checked_path(section, section=True)
            if not parent.is_dir() or not (parent / '_index.md').is_file():
                raise HTTPException(422, 'Choose an existing section')
            if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
                raise HTTPException(422, 'Slug must use lowercase letters, digits and hyphens')
            if slug == 'index' or (parent / slug).exists():
                raise HTTPException(409, 'This URL is reserved or already belongs to a section')
            path = '/'.join(filter(None, [section, slug + '.md']))
        else:
            path = data.get('path')
            if not isinstance(data.get('revision'), str):
                raise HTTPException(422, 'Base revision is required')
        for attempt in range(3):
            target = checked_path(path)
            if create:
                if target.exists():
                    raise HTTPException(409, 'A page with this slug already exists')
                metadata = {}
            else:
                existing = read_page(path)
                if not hmac.compare_digest(existing['revision'], data['revision']):
                    raise HTTPException(409, 'Page changed since it was opened; reload before saving')
                metadata, unused = parse(target.read_text())
            metadata['title'] = title
            yaml = YAML()
            yaml.preserve_quotes = True
            out = io.StringIO()
            yaml.dump(metadata, out)
            target.write_text('---\n' + out.getvalue() + '---\n\n' + body, encoding='utf-8')
            git('add', '--', PREFIX + '/' + path)
            if not git('diff', '--cached', '--name-only'):
                return {'commit': git('rev-parse', 'HEAD'), 'path': path, 'url': page_url(path), 'revision': git('hash-object', '--', str(target))}
            base_commit = git('rev-parse', 'HEAD')
            revision = git('hash-object', '--', str(target))
            git('-c', 'user.name=Socrat Wiki', '-c', 'user.email=wiki@alchemmist.xyz', 'commit', '-m', ('add' if create else 'update') + ' wiki page ' + path.lower())
            commit = git('rev-parse', 'HEAD')
            try:
                git('push', 'origin', 'HEAD:refs/heads/' + BRANCH)
                return {'commit': commit, 'path': path, 'url': page_url(path), 'revision': git('hash-object', '--', str(target))}
            except RuntimeError as error:
                sync()
                remote_commit = git('rev-parse', 'HEAD')
                if remote_commit == commit:
                    return {'commit': commit, 'path': path, 'url': page_url(path), 'revision': revision}
                try:
                    git('merge-base', '--is-ancestor', commit, remote_commit)
                    return {'commit': commit, 'path': path, 'url': page_url(path), 'revision': revision}
                except RuntimeError:
                    pass
                if remote_commit == base_commit:
                    raise RuntimeError('Repository push unavailable') from error
        raise HTTPException(409, 'Concurrent repository update; retry saving')


@app.middleware('http')
async def security(request: Request, call_next):
    if not GATEWAY_TOKEN or not hmac.compare_digest(GATEWAY_TOKEN, request.headers.get('x-socrat-editor-key', '')):
        return Response(status_code=403)
    try:
        peer = request.headers.get('x-socrat-wg-peer', '')
        if ipaddress.ip_address(peer) not in ipaddress.ip_network('10.250.0.0/24'):
            raise ValueError()
    except ValueError:
        return Response(status_code=403)
    origin = request.headers.get('origin')
    if origin and origin != ORIGIN:
        return Response(status_code=403)
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if origin != ORIGIN:
            return Response(status_code=403)
        with SESSION_LOCK:
            session = SESSIONS.get(request.cookies.get('wiki_editor_session', ''))
        if not session or session['peer'] != peer or session['expires'] < time.time() or not hmac.compare_digest(session['csrf'], request.headers.get('x-csrf-token', '')):
            return Response(status_code=403)
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > 2 * 1024 * 1024:
                return Response(status_code=413)
            chunks.append(chunk)
        request._body = b''.join(chunks)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/api/editor/session')
def session(request: Request, response: Response):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = time.time()
    with SESSION_LOCK:
        for old in list(SESSIONS):
            if SESSIONS[old]['expires'] < now:
                del SESSIONS[old]
        if len(SESSIONS) >= 10000:
            raise HTTPException(503, 'Too many editor sessions')
        SESSIONS[token] = {'csrf': csrf, 'peer': request.headers['x-socrat-wg-peer'], 'expires': now + 28800}
    response.set_cookie('wiki_editor_session', token, max_age=28800, secure=True, httponly=True, samesite='strict', path='/api/editor/')
    return {'writable': True, 'csrf_token': csrf}


@app.get('/api/editor/pages')
def get_page(path: str):
    with LOCK:
        sync()
        return read_page(path)


@app.get('/api/editor/catalog')
def catalog():
    with LOCK:
        sync()
        sections = []
        for item in sorted((WORK / PREFIX).rglob('_index.md')):
            relative = item.relative_to(WORK / PREFIX).as_posix()
            checked_path(relative)
            data = read_page(relative)
            section = str(Path(relative).parent)
            sections.append({'path': '' if section == '.' else section, 'title': data['title']})
        return {'sections': sections}


@app.put('/api/editor/pages')
def update_page(data: dict):
    return save(data)


@app.post('/api/editor/pages')
def create_page(data: dict):
    return save(data, create=True)


@app.post('/api/editor/preview')
def preview(data: dict):
    title, body = fields(data)
    if data.get('path'):
        checked_path(data['path'])
    def relref(match):
        path = match.group(1).lstrip('/')
        checked_path(path)
        return page_url(path)
    body = re.sub(r'{{[<%]\s*relref\s+"([^"]+)"\s*[>%]}}', relref, body)
    return {'html': MarkdownIt('commonmark', {'html': False}).enable('table').render(body), 'approximate': True}


@app.get('/api/editor/publications/{commit}')
def publication(commit: str):
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise HTTPException(400, 'Invalid commit')
    try:
        with urllib.request.urlopen(ORIGIN + '/version.json', timeout=10) as response:
            published = json.load(response).get('source_sha', '')
        if published == commit:
            status = 'published'
        elif re.fullmatch(r'[a-f0-9]{40}', published):
            with LOCK:
                sync()
                try:
                    git('merge-base', '--is-ancestor', commit, published)
                    status = 'published'
                except RuntimeError:
                    status = 'pending'
        else:
            status = 'pending'
    except Exception:
        status = 'pending'
    return {'status': status, 'url': ORIGIN + '/'}
