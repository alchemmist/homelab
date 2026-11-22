"""Source contracts for the read-only Gatus proxy that preserves legacy Kuma URLs."""

import pytest

from tests.public_entry_contract import assert_read_only_status_policy, render


@pytest.fixture(scope="module")
def rendered_policy() -> str:
    """Inspect the ConfigMap actually emitted by the owner chart, without a cluster."""
    [config] = [d for d in render("uptime-kuma") if d["kind"] == "ConfigMap"]
    return config["data"]["nginx.conf"]


def test_public_read_only_status_and_legacy_https_redirect(
    rendered_policy: str,
) -> None:
    """The only proxy pass is inside the allowlist; socket, push and admin paths default to 404."""
    assert_read_only_status_policy(rendered_policy)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "upstream kuma {",
            "upstream kuma { server dummy.invalid:80; }\nupstream unused {",
        ),
        ("gatus.uptime-kuma.svc.cluster.local:80", "dummy.invalid:80"),
        ("^(GET|HEAD)$", "^(GET|HEAD|POST)$"),
        ("endpoints/|suites/|favicon", "socket.io|endpoints/|suites/|favicon"),
        ("return 302 /;", "return 302 http://gatus:8080/;"),
        ("location / { return 404; }", "location / { proxy_pass http://kuma; }"),
    ],
)
def test_proxy_rejects_unsafe_mutations(rendered_policy: str, old: str, new: str) -> None:
    """Mutate the real policy only after passing the positive control."""
    assert_read_only_status_policy(rendered_policy)
    assert old in rendered_policy
    with pytest.raises(AssertionError):
        assert_read_only_status_policy(rendered_policy.replace(old, new))
