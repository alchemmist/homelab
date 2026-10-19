import base64
import json
import subprocess
import urllib.request


def kubectl(*args):
    return subprocess.check_output(['kubectl', '-n', 'llm', *args], text=True)


secret = json.loads(kubectl('get', 'secret', 'litellm-env', '-o', 'json'))
key = base64.b64decode(secret['data']['LITELLM_MASTER_KEY']).decode()
address = kubectl('get', 'svc', 'litellm', '-o', 'jsonpath={.spec.clusterIP}')
base = 'http://' + address + ':4000'
headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
urls = {
    'logo_url': 'https://llm.alchemmist.xyz/branding/socrat-logo-light-v1.svg',
    'logo_url_dark': 'https://llm.alchemmist.xyz/branding/socrat-logo-dark-v1.svg',
    'favicon_url': 'https://llm.alchemmist.xyz/branding/socrat-icon-v1.png',
}


def request(path, payload=None, method=None):
    req = urllib.request.Request(
        base + path,
        headers=headers,
        method=method or ('GET' if payload is None else 'PATCH'),
        data=None if payload is None else json.dumps(payload).encode(),
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


for url in set(urls.values()):
    with urllib.request.urlopen(url, timeout=30) as response:
        if response.headers.get_content_type() != ('image/svg+xml' if url.endswith('.svg') else 'image/png'):
            raise RuntimeError('Brand asset returned an unexpected content type')
current = request('/get/ui_theme_settings')['values']
if any(current.get(name) != url for name, url in urls.items()):
    request('/config/update', {'general_settings': {'store_model_in_db': True}}, method='POST')
    request('/update/ui_theme_settings', {**current, **urls})
    print('updated branding')
else:
    print('branding unchanged')
actual = request('/get/ui_theme_settings')['values']
if any(actual.get(name) != url for name, url in urls.items()):
    raise RuntimeError('Branding readback failed')
print('branding verified')
