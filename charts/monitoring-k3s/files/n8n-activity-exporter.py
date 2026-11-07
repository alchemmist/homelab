"""Read-only, bounded n8n execution metadata poller. Never fetches execution data."""
import datetime as dt
import json
import os
import socketserver
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.environ.get('N8N_URL', 'http://n8n.automation.svc.cluster.local')
LOCK = threading.Lock()
STATE = {'ok': 0, 'at': 0, 'counts': {}}


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def summarize(rows, now):
    counts = {(status, window): 0 for status in ('success', 'error', 'running', 'waiting', 'other') for window in (300, 3600)}
    seen = set()
    for row in rows:
        if row['id'] in seen:
            continue
        seen.add(row['id'])
        if not row.get('startedAt'):
            continue
        age = now - timestamp(row['startedAt'])
        status = row['status'] if row['status'] in ('success', 'error', 'running', 'waiting') else 'other'
        for window in (300, 3600):
            if 0 <= age < window:
                counts[status, window] += 1
    return counts


def get_page(cursor=None, status=None):
    params = {'limit': 100, 'includeData': 'false'}
    if cursor:
        params['cursor'] = cursor
    if status:
        params['status'] = status
    key = open('/secrets/api-key', encoding='utf-8').read().strip()
    request = urllib.request.Request(BASE + '/api/v1/executions?' + urllib.parse.urlencode(params), headers={'X-N8N-API-KEY': key})
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.load(response)


def collect():
    # History is sorted by descending execution ID. Count recent starts by
    # current outcome, not recent completions of arbitrarily old executions.
    now = time.time()
    rows, cursor = [], None
    for _ in range(40):
        page = get_page(cursor)
        rows.extend(page['data'])
        cursor = page.get('nextCursor')
        dates = [timestamp(r['startedAt']) for r in page['data'] if r.get('startedAt')]
        if not cursor or (dates and max(dates) < now - 3600):
            break
    else:
        raise RuntimeError('recent-start scan exceeds 4000 execution budget')
    # The unfiltered API deliberately excludes active executions. Fetch them
    # explicitly. Waiting workflows are not actively running.
    active, cursor = [], None
    for _ in range(10):
        page = get_page(cursor, 'running')
        active.extend(page['data'])
        cursor = page.get('nextCursor')
        if not cursor:
            break
    else:
        raise RuntimeError('running scan incomplete')
    result = summarize(rows + active, now)
    result['running', 0] = len({r['id'] for r in active if r.get('status') == 'running'})
    return result


def loop():
    while True:
        try:
            counts = collect()
            with LOCK:
                STATE.update(ok=1, at=time.time(), counts=counts)
        except Exception:
            # Do not log response bodies, workflow metadata or API credentials.
            with LOCK:
                STATE['ok'] = 0
        time.sleep(30)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/metrics':
            self.send_error(404)
            return
        with LOCK:
            state = dict(STATE)
        fresh = int(state['ok'] and time.time() - state['at'] < 90)
        lines = ['# TYPE socrat_n8n_collection_success gauge', f'socrat_n8n_collection_success {fresh}', '# TYPE socrat_n8n_collection_timestamp_seconds gauge', f'socrat_n8n_collection_timestamp_seconds {state["at"]}', '# TYPE socrat_n8n_starts_window gauge']
        if fresh:
            for (status, window), count in sorted(state['counts'].items()):
                lines.append(f'socrat_n8n_starts_window{{status="{status}",window="{window}"}} {count}')
        payload = ('\n'.join(lines) + '\n').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass


class MetricsServer(ThreadingHTTPServer):
    def server_bind(self):
        # Avoid slow reverse DNS lookups during HTTPServer initialization.
        socketserver.TCPServer.server_bind(self)
        self.server_name = 'n8n-observer'
        self.server_port = self.server_address[1]


if __name__ == '__main__':
    threading.Thread(target=loop, daemon=True).start()
    MetricsServer(('0.0.0.0', 9189), Handler).serve_forever()
