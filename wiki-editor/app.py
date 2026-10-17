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
        if create and data.get('tree_revision') and data['tree_revision'] != content_revision():
            raise HTTPException(409, 'Wiki structure or content changed; reload before saving')
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
                if data.get('tree_revision') and data['tree_revision'] != content_revision():
                    raise HTTPException(409, 'Wiki structure or content changed; reload before saving')
                assert_available_url(page_url(path))
                siblings = tree_nodes(section)
                renumber(siblings)
                metadata = {'weight': (len(siblings) + 1) * 10}
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
            git('add', '--', PREFIX if create else PREFIX + '/' + path)
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


def write_markdown(target, metadata, body):
    yaml = YAML()
    yaml.preserve_quotes = True
    out = io.StringIO()
    yaml.dump(metadata, out)
    target.write_text('---\n' + out.getvalue() + '---\n\n' + body, encoding='utf-8')


def content_revision():
    return git('rev-parse', 'HEAD:' + PREFIX)


def node_metadata(node):
    path = node['id']
    if node['kind'] == 'folder':
        path += '/_index.md'
    elif not path.endswith('.md'):
        path += '/index.md'
    return checked_path(path)


def document_url(path, metadata):
    custom = metadata.get('url')
    if custom:
        if not isinstance(custom, str) or not custom.startswith('/') or custom.startswith('//'):
            raise HTTPException(422, 'Unsupported page URL')
        return ORIGIN + custom
    if metadata.get('slug'):
        parent = str(Path(path).parent)
        if Path(path).name == 'index.md':
            parent = str(Path(parent).parent)
        return ORIGIN + '/' + '/'.join(filter(None, [parent if parent != '.' else '', str(metadata['slug'])])) + '/'
    return page_url(path)


def tree_nodes(parent=''):
    directory = checked_path(parent, section=True)
    result = []
    for item in directory.iterdir():
        if item.name.startswith('.'):
            raise HTTPException(422, 'Hidden content paths are not supported')
        if item.is_symlink():
            raise HTTPException(422, 'Symbolic links are not supported')
        relative = item.relative_to(WORK / PREFIX).as_posix()
        if item.is_dir():
            checked_path(relative, section=True)
            if (item / '_index.md').is_file():
                source, kind = item / '_index.md', 'folder'
                children = tree_nodes(relative)
            elif (item / 'index.md').is_file():
                source, kind, children = item / 'index.md', 'page', []
                for asset in item.rglob('*'):
                    if asset.name.startswith('.'):
                        raise HTTPException(422, 'Hidden content paths are not supported')
                    if asset.is_symlink():
                        raise HTTPException(422, 'Symbolic links are not supported')
            else:
                raise HTTPException(422, 'Folders must contain _index.md or index.md')
        elif item.suffix == '.md' and item.name not in ('_index.md', 'index.md'):
            source, kind, children = item, 'page', []
        else:
            continue
        checked_path(source.relative_to(WORK / PREFIX).as_posix())
        metadata, body = parse(source.read_text(encoding='utf-8'))
        try:
            weight = int(metadata.get('weight', 0))
        except (ValueError, TypeError):
            raise HTTPException(422, 'Page weight must be an integer')
        result.append({'id': relative, 'path': relative, 'page_path': source.relative_to(WORK / PREFIX).as_posix(), 'kind': kind, 'title': str(metadata.get('title', item.stem)), 'weight': weight,
                       'url': document_url(source.relative_to(WORK / PREFIX).as_posix(), metadata), 'children': children})
    return sorted(result, key=lambda node: (node['weight'] == 0, node['weight'], node['title'].casefold(), node['id']))


def tree_result():
    return {'revision': content_revision(), 'nodes': tree_nodes()}


def flatten_nodes(nodes):
    return {node['id']: node for root in nodes for node in [root, *flatten_nodes(root['children']).values()]}


def section_parent(value):
    parent = checked_path(value, section=True)
    if not parent.is_dir() or not (parent / '_index.md').is_file():
        raise HTTPException(422, 'Choose an existing folder')
    checked_path('/'.join(filter(None, [value, '_index.md'])))
    return parent


def assert_available_url(url):
    wanted = url.rstrip('/')
    for node in flatten_nodes(tree_nodes()).values():
        metadata, body = parse(node_metadata(node).read_text(encoding='utf-8'))
        aliases = metadata.get('aliases', [])
        if not isinstance(aliases, list):
            raise HTTPException(422, 'Page aliases must be a list')
        urls = [node['url'], *[ORIGIN + alias for alias in aliases if isinstance(alias, str)]]
        if any(existing.rstrip('/') == wanted for existing in urls):
            raise HTTPException(409, 'This URL belongs to another page or redirect')


def renumber(nodes):
    for index, node in enumerate(nodes, 1):
        target = node_metadata(node)
        metadata, body = parse(target.read_text(encoding='utf-8'))
        if metadata.get('weight') != index * 10:
            metadata['weight'] = index * 10
            write_markdown(target, metadata, body)


def publish_structure(data, operation):
    revision = data.get('revision')
    if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise HTTPException(422, 'Content tree revision is required')
    with LOCK:
        sync()
        for attempt in range(3):
            if not hmac.compare_digest(content_revision(), revision):
                raise HTTPException(409, 'Wiki structure or content changed; reload before saving')
            try:
                extra = operation()
                git('add', '--', PREFIX)
                base = git('rev-parse', 'HEAD')
                if not git('diff', '--cached', '--name-only'):
                    return dict(tree_result(), commit=base, **extra)
                git('-c', 'user.name=Socrat Wiki', '-c', 'user.email=wiki@alchemmist.xyz', 'commit', '-m', 'update wiki structure')
                commit = git('rev-parse', 'HEAD')
                result = dict(tree_result(), commit=commit, **extra)
                try:
                    git('push', 'origin', 'HEAD:refs/heads/' + BRANCH)
                    return result
                except RuntimeError as error:
                    sync()
                    remote = git('rev-parse', 'HEAD')
                    try:
                        git('merge-base', '--is-ancestor', commit, remote)
                        return dict(tree_result(), commit=commit, **extra)
                    except RuntimeError:
                        if remote == base:
                            raise RuntimeError('Repository push unavailable') from error
            except Exception:
                git('reset', '--hard', 'HEAD')
                git('clean', '-fd', '--', PREFIX)
                raise
        raise HTTPException(409, 'Concurrent repository update; retry saving')


@app.get('/api/editor/tree')
def get_tree():
    with LOCK:
        sync()
        return tree_result()


@app.post('/api/editor/folders')
def create_folder(data: dict):
    title, unused = fields(dict(data, body=''))
    slug, parent_id = data.get('slug'), data.get('parent', '')
    if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) or slug == 'index':
        raise HTTPException(422, 'Slug must use lowercase letters, digits and hyphens')
    def operation():
        parent = section_parent(parent_id)
        siblings = tree_nodes(parent_id)
        destination = parent / slug
        if destination.exists() or (parent / (slug + '.md')).exists():
            raise HTTPException(409, 'This name is already used')
        assert_available_url(page_url(destination.relative_to(WORK / PREFIX).as_posix() + '/_index.md'))
        destination.mkdir()
        write_markdown(destination / '_index.md', {'title': title, 'weight': (len(siblings) + 1) * 10}, '')
        renumber(siblings)
        path = destination.relative_to(WORK / PREFIX).as_posix()
        return {'path': path + '/_index.md', 'url': page_url(path + '/_index.md')}
    return publish_structure(data, operation)


def rewrite_references(documents, moved):
    import posixpath
    lookup = {}
    for path in documents:
        variants = [path, path.removesuffix('.md')]
        if Path(path).name in ('_index.md', 'index.md'):
            variants.append(str(Path(path).parent))
        for variant in variants:
            lookup[variant.strip('/')] = path
    expression = re.compile(r'({{[<%]\s*relref\s+["\'])([^"\']+)(["\']\s*[>%]}})')
    for old_path, (metadata, body) in documents.items():
        new_path = moved.get(old_path, old_path)
        old_url, new_url = document_url(old_path, metadata), document_url(new_path, metadata)
        if old_url != new_url:
            aliases = metadata.get('aliases', [])
            if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
                raise HTTPException(422, 'Page aliases must be a list')
            aliases = [alias for alias in aliases if alias != new_url.removeprefix(ORIGIN)]
            previous = old_url.removeprefix(ORIGIN)
            if previous not in aliases:
                aliases.append(previous)
            metadata['aliases'] = aliases
        def replace(match):
            reference, separator, fragment = match[2].partition('#')
            relative = posixpath.normpath(posixpath.join(str(Path(old_path).parent), reference)).strip('/')
            candidates = [reference.strip('/')] if reference.startswith('/') else [relative, reference.strip('/')]
            resolved = old_path if not reference else next((lookup[candidate] for candidate in candidates if candidate in lookup), None)
            if resolved is None or (resolved not in moved and old_path not in moved):
                return match[0]
            return match[1] + '/' + moved.get(resolved, resolved) + (separator + fragment if separator else '') + match[3]
        rewritten = expression.sub(replace, body)
        if new_path != old_path or rewritten != body:
            write_markdown(checked_path(new_path), metadata, rewritten)


@app.post('/api/editor/move')
def move_node(data: dict):
    source, parent_id, before = data.get('source'), data.get('target_parent', ''), data.get('before')
    def operation():
        source_path = checked_path(source, section=True)
        if not source or Path(source).name in ('_index.md', 'index.md'):
            raise HTTPException(422, 'The root and section index cannot be moved')
        nodes = flatten_nodes(tree_nodes())
        if source not in nodes:
            raise HTTPException(404, 'Source not found')
        node = nodes[source]
        parent = section_parent(parent_id)
        if parent_id == source or parent_id.startswith(source + '/'):
            raise HTTPException(422, 'A folder cannot be moved into itself')
        old_parent = str(Path(source).parent)
        old_parent = '' if old_parent == '.' else old_parent
        siblings = [item for item in tree_nodes(parent_id) if item['id'] != source]
        if before is not None and before not in [item['id'] for item in siblings]:
            raise HTTPException(422, 'Insertion target must be a sibling')
        destination = parent / source_path.name
        destination_id = destination.relative_to(WORK / PREFIX).as_posix()
        if destination != source_path:
            collision = parent / (source_path.stem if source_path.suffix == '.md' else source_path.name + '.md')
            if destination.exists() or collision.exists():
                raise HTTPException(409, 'A page or folder with this name already exists')
            documents = {}
            for path in (WORK / PREFIX).rglob('*.md'):
                relative = path.relative_to(WORK / PREFIX).as_posix()
                checked_path(relative)
                documents[relative] = parse(path.read_text(encoding='utf-8'))
            moved = {path: destination_id + path[len(source):] for path in documents if path == source or path.startswith(source + '/')}
            occupied = {}
            for path, (metadata, body) in documents.items():
                aliases = metadata.get('aliases', [])
                if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.startswith('/') or alias.startswith('//') or '..' in alias.split('/') for alias in aliases):
                    raise HTTPException(422, 'Aliases must be absolute site paths')
                if path in moved and (metadata.get('slug') or metadata.get('url')):
                    raise HTTPException(422, 'Moving pages with custom slug or URL is not supported')
                for url in [document_url(path, metadata), *[ORIGIN + alias for alias in aliases]]:
                    occupied.setdefault(url.rstrip('/'), set()).add(path)
            for old_path, new_path in moved.items():
                metadata, body = documents[old_path]
                owners = occupied.get(document_url(new_path, metadata).rstrip('/'), set())
                if owners - {old_path}:
                    raise HTTPException(409, 'Destination URL belongs to another page or redirect')
            source_path.rename(destination)
            rewrite_references(documents, moved)
            renumber(tree_nodes(old_parent))
        node = dict(node, id=destination_id)
        index = next((index for index, item in enumerate(siblings) if item['id'] == before), len(siblings))
        siblings.insert(index, node)
        renumber(siblings)
        target = node_metadata(node)
        metadata, unused = parse(target.read_text(encoding='utf-8'))
        path = target.relative_to(WORK / PREFIX).as_posix()
        return {'path': path, 'url': document_url(path, metadata)}
    return publish_structure(data, operation)


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
