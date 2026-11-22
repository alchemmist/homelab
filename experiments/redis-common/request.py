"""Local fixture only. Send requests to a particular worker's loopback."""
import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

mode = sys.argv[1]
if mode == 'key':
    route, key, payload = '/key/generate', 'sk-fixture-master', {'rpm_limit': 1, 'models': ['fixture']}
else:
    route, key, payload = '/v1/chat/completions', sys.stdin.read().strip(), {
        'model': 'fixture', 'messages': [{'role': 'user', 'content': 'fixture'}]}
req = Request('http://127.0.0.1:4000' + route, data=json.dumps(payload).encode(),
              headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
try:
    with urlopen(req, timeout=20) as response:
        data = json.load(response)
        if mode == 'key':
            print(data['key'])
        else:
            assert data['choices'][0]['message']['content'] == 'fixture-response'
            print(response.status)
except HTTPError as exc:
    if mode == 'key':
        raise
    print(exc.code)
