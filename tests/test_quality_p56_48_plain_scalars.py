"""Redundant YAML quotes stay off strings that already parse as text."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

AUTHENTIK_TAG = "    tag: 2026.8.5"
MONITORING_LINES = (
    "      rancher_url: https://rancher.socrat.alchemmist.xyz/dashboard/c/local/explorer",
    (
        "      rancher_url: https://rancher.socrat.alchemmist.xyz/dashboard/c/local/"
        "explorer/pod/{{ $labels.namespace }}/{{ $labels.pod }}"
    ),
    (
        "      rancher_url: https://rancher.socrat.alchemmist.xyz/dashboard/c/local/"
        "explorer/node/{{ $labels.node }}"
    ),
    r"        regex: 10\.250\.0\.(1|3|5):6443",
    (
        r"        regex: (192\.168\.0\.(23|24)|10\.250\.0\.5):10250;"
        r"(apiserver|etcd|scheduler|workqueue|kubeproxy)_.*"
    ),
)


def test_authentik_image_tag_is_a_plain_version_string() -> None:
    """The pinned authentik tag keeps its text without quote characters."""
    text = (ROOT / "deploy/authentik/values.yaml").read_text(encoding="utf-8")
    assert AUTHENTIK_TAG in text.splitlines()
    assert "tag: '2026.8.5'" not in text
    assert 'tag: "2026.8.5"' not in text


def test_monitoring_annotation_and_relabel_scalars_are_plain() -> None:
    """Rancher URLs and relabel regexes keep their characters without quotes."""
    text = (ROOT / "deploy/monitoring/values.yaml").read_text(encoding="utf-8")
    lines = text.splitlines()
    for expected in MONITORING_LINES:
        assert expected in lines
        assert f"'{expected.split(': ', 1)[1]}'" not in text


def test_transit_worker_fence_message_is_plain() -> None:
    """The enrollment refusal text stays the same without quote characters."""
    text = (ROOT / "ansible/playbooks/k3s-transit-worker.yml").read_text(encoding="utf-8")
    message = (
        "Native gateway is fenced. Use the explicit, reviewed rollback "
        "instead of worker enrollment."
    )
    assert f"fail_msg: {message}" in text
    assert f"fail_msg: '{message}'" not in text
