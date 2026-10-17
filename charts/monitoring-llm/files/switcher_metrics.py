import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


URL = 'http://llm-switcher.llm.svc.cluster.local:8000/status'
KEY = os.environ['SWITCHER_API_KEY']


def label(value):
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


def collect():
    request = urllib.request.Request(URL, headers={'Authorization': 'Bearer ' + KEY})
    with urllib.request.urlopen(request, timeout=5) as response:
        data = json.load(response)
    if not isinstance(data.get('running'), bool) or not isinstance(data.get('waiting'), dict):
        raise ValueError('Invalid status schema')
    lines = ['llm_switcher_scrape_success 1',
             'llm_switcher_requests_running ' + str(int(data['running']))]
    for model, count in sorted(data['waiting'].items()):
        if type(count) is not int or count < 0:
            raise ValueError('Invalid queue size')
        lines.append('llm_switcher_requests_waiting{model="' + label(model) + '"} ' + str(count))
    if data.get('loaded_model'):
        lines.append('llm_switcher_loaded_model{model="' + label(data['loaded_model']) + '"} 1')
    return '\n'.join(lines) + '\n'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            body = b'ok\n'
        elif self.path == '/metrics':
            try:
                body = collect().encode()
            except Exception:
                body = b'llm_switcher_scrape_success 0\n'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 9108), Handler).serve_forever()
