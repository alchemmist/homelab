import argparse
import html
import ipaddress
import json
import re
import sys
import time
import urllib.parse
import urllib.request


FIELDS = ('ip', 'local_port', 'protocol', 'remote_ip', 'external_port', 'wan', 'status', 'comment')


def parse_forwards(page):
    rows = []
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', page, re.S | re.I):
        selected = re.search(r'name="(select\d+)"', row)
        if not selected:
            continue
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S | re.I)
        values = [html.unescape(re.sub(r'<[^>]*>', '', cell)).strip() for cell in cells]
        if len(values) != 9:
            raise ValueError('Unexpected router forwarding table format')
        entry = dict(zip(FIELDS, values[:8]))
        entry['selector'] = selected.group(1)
        rows.append(entry)
    if not rows:
        raise ValueError('Missing router forwarding table')
    return rows


def canonical(rows):
    return sorted(tuple(row[field] for field in FIELDS) for row in rows)


class Router:
    def __init__(self, credentials, address):
        self.base = 'http://' + str(ipaddress.IPv4Address(address))
        self.cookie = None
        page = self.request('/login.htm')
        match = re.search(r"var map2 = '(.*?)';", page)
        if not match:
            raise ValueError('Unsupported router authentication page')
        alphabet = match.group(1).replace('\\\\', '\\').replace("\\'", "'")
        plain = credentials['username'] + credentials['password']
        if any(ord(char) < 32 or ord(char) - 32 >= len(alphabet) for char in plain):
            raise ValueError('Unsupported credential character')
        credit = ''.join(alphabet[ord(char) - 32] for char in plain)
        page = self.request('/boafrm/formLoginCookie', {
            'credit': credit, 'login': '', 'pass': '', 'next_link': '/', 'continue': 'Войти',
        })
        match = re.search(r'document.cookie = "(cookie_auth=[^;"\r\n]+)', page)
        if not match:
            raise ValueError('Router authentication failed')
        self.cookie = match.group(1)

    def request(self, path, data=None):
        encoded = None if data is None else urllib.parse.urlencode(data).encode()
        headers = {} if self.cookie is None else {'Cookie': self.cookie}
        request = urllib.request.Request(self.base + path, data=encoded, headers=headers)
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode('utf-8')

    def forwards(self):
        return parse_forwards(self.request('/portfw.htm'))

    def verify(self, expected):
        for attempt in range(5):
            rows = self.forwards()
            if canonical(rows) == canonical(expected):
                return rows
            if attempt < 4:
                time.sleep(1)
        raise RuntimeError('Router forwarding readback does not match expected state')

    def replace(self, expected_rows, old, new):
        rows = self.verify(expected_rows)
        matching = [row for row in rows if canonical([row]) == canonical([old])]
        if len(matching) != 1:
            raise RuntimeError('Expected old forward is not unique')
        remaining = [row for row in rows if row is not matching[0]]
        try:
            self.request('/boafrm/formPortFw', {
                matching[0]['selector']: 'ON', 'deleteSelPortFw': 'Удалить выбранное',
                'submit-url': '/portfw.htm',
            })
            self.verify(remaining)
            self.add(new)
            return self.verify(remaining + [new])
        except Exception:
            current = self.forwards()
            if canonical(current) == canonical(remaining + [new]):
                return current
            if canonical(current) == canonical(remaining):
                self.add(old)
                self.verify(remaining + [old])
            raise

    def add(self, row):
        if row['protocol'] != 'TCP' or row['wan'] != 'Wan2' or row['status'] != 'Enabled':
            raise ValueError('Only enabled WAN2 TCP forwarding is supported')
        self.request('/boafrm/formPortFw', {
            'enabled': 'ON', 'WAN2': 'ON', 'ip': row['ip'], 'protocol': '1',
            'fromPort': row['local_port'], 'toPort': row['local_port'],
            'externalFromPort': row['external_port'], 'externalToPort': row['external_port'],
            'rmtip': row['remote_ip'], 'comment': row['comment'],
            'save_apply': 'Применить', 'addPortFwFlag': '1', 'submit-url': '/portfw.htm',
        })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', default='192.168.0.1')
    parser.add_argument('--expected-old')
    parser.add_argument('--destination')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    router = Router(json.load(sys.stdin), args.router)
    rows = router.forwards()
    if not args.apply:
        print(json.dumps({'forwards': rows}, indent=2))
        return
    if not args.expected_old or not args.destination:
        parser.error('--apply requires --expected-old and --destination')
    old_ip = str(ipaddress.IPv4Address(args.expected_old))
    destination = str(ipaddress.IPv4Address(args.destination))
    if old_ip == destination:
        raise ValueError('Old and destination addresses must differ')
    targets = []
    for port, comment in [('80', 'socrat-http'), ('443', 'socrat-https')]:
        matches = [row for row in rows if row['external_port'] == port]
        expected = dict(zip(FIELDS, [old_ip, port, 'TCP', '0.0.0.0', port, 'Wan2', 'Enabled', comment]))
        if len(matches) != 1 or canonical(matches) != canonical([expected]):
            raise RuntimeError('Forward does not match explicit expected old state: ' + port)
        targets.append(matches[0])
    completed = []
    try:
        for old in targets:
            new = dict(old, ip=destination)
            rows = router.replace(rows, old, new)
            completed.append((old, new))
    except Exception:
        for old, new in reversed(completed):
            rows = router.replace(rows, new, old)
        raise
    print(json.dumps({'changed': True, 'forwards': rows}, indent=2))


if __name__ == '__main__':
    main()
