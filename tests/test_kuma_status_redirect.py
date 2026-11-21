"""Source contracts for the read-only Gatus proxy that preserves legacy Kuma URLs."""

import pytest

from tests.public_entry_contract import assert_status_upstream, render

PUBLIC_PATHS = (
    r"^/(?:$|css/|js/|img/|fonts/|assets/|endpoints/|suites/|favicon|apple-touch-icon|"
    r"manifest\.json|robots\.txt|api/v1/(?:config$|endpoints/|suites/))"
)


@pytest.fixture(scope="module")
def rendered_policy() -> str:
    """Inspect the ConfigMap actually emitted by the owner chart, without a cluster."""
    [config] = [d for d in render("uptime-kuma") if d["kind"] == "ConfigMap"]
    return config["data"]["nginx.conf"]


def _guard(conf: str) -> None:
    """Require the full server body: no hidden write location or fallback backend."""
    directives = [
        line.strip()
        for line in conf.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert directives.count("server {") == 1
    assert_status_upstream(conf)
    assert directives[directives.index("server {") + 1 :] == [
        "listen 8080;",
        "absolute_redirect off;",
        "proxy_set_header Host status.alchemmist.xyz;",
        "proxy_set_header X-Forwarded-Proto https;",
        'proxy_set_header Upgrade "";',
        "proxy_set_header Connection close;",
        "if ($request_method !~ ^(GET|HEAD)$) { return 405; }",
        "if ($host = kuma.socrat.alchemmist.xyz) { return 302 https://status.alchemmist.xyz/; }",
        "location = /status/socrat { return 302 /; }",
        "location = /status/socrat/ { return 302 /; }",
        "location ~ " + PUBLIC_PATHS + " {",
        "proxy_pass http://kuma;",
        "}",
        "location / { return 404; }",
        "}",
        "}",
    ]


def test_public_read_only_status_and_legacy_https_redirect(rendered_policy: str) -> None:
    """The only proxy pass is inside the allowlist; socket, push and admin paths default to 404."""
    _guard(rendered_policy)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("upstream kuma {", "upstream kuma { server dummy.invalid:80; }\nupstream unused {"),
        ("^(GET|HEAD)$", "^(GET|HEAD|POST)$"),
        ("endpoints/|suites/|favicon", "socket.io|endpoints/|suites/|favicon"),
        ("return 302 /;", "return 302 http://gatus:8080/;"),
        ("location / { return 404; }", "location / { proxy_pass http://kuma; }"),
    ],
)
def test_proxy_rejects_unsafe_mutations(rendered_policy: str, old: str, new: str) -> None:
    """Mutate the real policy only after passing the positive control."""
    _guard(rendered_policy)
    assert old in rendered_policy
    with pytest.raises(AssertionError):
        _guard(rendered_policy.replace(old, new))
