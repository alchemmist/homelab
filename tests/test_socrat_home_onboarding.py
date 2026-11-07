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


def test_onboarding_is_between_title_and_wiki_navigation():
    assert HTML.index('</h1>') < HTML.index('class="onboarding"') < HTML.index('<nav ')
    assert 'with your assigned username and password, then change your password.' in HTML
    assert 'to connect to the internal network.' in HTML
    assert 'Then explore the cluster and its services.' in HTML
    assert 'explore the wiki &gt;' in HTML
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


def test_onboarding_uses_the_existing_courier_font():
    assert "font:15px/1.75 CourierCyr,monospace}.onboarding p" in HTML


def test_links_use_body_color_without_extra_word_emphasis():
    assert ".onboarding a{display:inline;padding:0;font:inherit;color:inherit;" in HTML
    assert ".copy nav a{color:var(--muted);text-decoration:underline;" in HTML
    assert ".copy a:hover{color:var(--muted)}" in HTML
    assert "<strong" not in HTML and "<em>" not in HTML
