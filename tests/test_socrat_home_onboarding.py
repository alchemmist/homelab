"""Keep the public welcome copy short and its onboarding links intentional."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'charts/socrat-home/files/index.html').read_text()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.urls.append(dict(attrs)['href'])


def test_onboarding_is_under_title_with_one_final_wiki_sentence():
    assert HTML.index('</h1>') < HTML.index('class="onboarding"')
    assert 'with your assigned username and password, then change your password.' in HTML
    assert 'to connect to the internal network.' in HTML
    assert '<p><a href="https://wiki.socrat.alchemmist.xyz/">Then explore the cluster and its services with wiki.</a></p>' in HTML
    assert '<nav ' not in HTML
    assert 'explore the wiki &gt;' not in HTML
    assert 'start from wiki' not in HTML


def test_onboarding_links_use_canonical_hosts_and_netbird_heading():
    parser = Links()
    parser.feed(HTML)
    assert len(parser.urls) == 3
    assert parser.urls[0] == 'https://auth.socrat.alchemmist.xyz/'
    netbird = urlsplit(parser.urls[1])
    assert netbird.scheme == 'https'
    assert netbird.netloc == 'wiki.socrat.alchemmist.xyz'
    assert netbird.path == '/network/vpn/'
    assert unquote(netbird.fragment) == 'netbird--для-администраторов-узлов'
    assert parser.urls[2] == 'https://wiki.socrat.alchemmist.xyz/'


def test_inline_links_and_existing_artwork_are_preserved():
    assert '.onboarding a{display:inline;padding:0;font:inherit;' in HTML
    assert '<h1 id="title">welcome to<br><span>socrat cluster</span></h1>' in HTML
    assert '<img src="/wallpaper.webp"' in HTML
    assert '<script' not in HTML


def test_heading_stays_courier_and_prose_uses_wiki_serif():
    assert 'h1{font-family:CourierCyr,monospace;' in HTML
    assert 'font:18px/1.6 "Computer Modern Roman",serif}.onboarding p' in HTML
    assert '.onboarding a{display:inline;padding:0;font:inherit;' in HTML


def test_links_use_body_color_without_extra_word_emphasis():
    assert ".onboarding a{display:inline;padding:0;font:inherit;color:inherit;" in HTML
    assert 'color:inherit;text-decoration:underline;' in HTML
    assert ".copy a:hover{color:var(--muted)}" in HTML
    assert "<strong" not in HTML and "<em>" not in HTML


def test_wiki_font_is_self_hosted_and_mounted():
    import base64
    import hashlib
    import subprocess
    import yaml

    font = (ROOT / 'charts/socrat-home/files/cmu.serif-roman.woff2').read_bytes()
    assert hashlib.sha256(font).hexdigest() == '7b78810e9e0c44d1088e837c8efba0a8e58f46330b93bf3dd49e86ae1d2f6c47'
    rendered = subprocess.check_output(['helm', 'template', 'home', str(ROOT / 'charts/socrat-home'), '-f', str(ROOT / 'deploy/socrat-home/values.yaml')], text=True)
    objects = list(yaml.safe_load_all(rendered))
    cm = next(o for o in objects if o and o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'home-index')
    assert base64.b64decode(cm['binaryData']['cmu.serif-roman.woff2']) == font
    deploy = next(o for o in objects if o and o['kind'] == 'Deployment')
    mounts = deploy['spec']['template']['spec']['containers'][0]['volumeMounts']
    assert any(m['mountPath'] == '/usr/share/nginx/html/fonts/cmu.serif-roman.woff2' and m['readOnly'] for m in mounts)
