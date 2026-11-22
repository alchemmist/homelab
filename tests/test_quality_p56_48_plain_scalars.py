"""YAML scalar formatting must preserve the strings consumed by the deployments."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXPLORER = "https://rancher.socrat.alchemmist.xyz/dashboard/c/local/explorer"


def test_authentik_image_tag_is_a_version_string() -> None:
    """The pinned authentik tag is text, not a number or a quoted payload."""
    values = yaml.safe_load((ROOT / "deploy/authentik/values.yaml").read_text(encoding="utf-8"))
    assert values["global"]["image"]["tag"] == "2026.8.5"


def test_monitoring_annotation_and_relabel_scalars_keep_exact_values() -> None:
    """Each rule receives its URL and each relabeling its unmodified regex."""
    values = yaml.safe_load((ROOT / "deploy/monitoring/values.yaml").read_text(encoding="utf-8"))
    annotations = values["defaultRules"]["additionalRuleAnnotations"]
    for name in ("KubeMemoryOvercommit", "KubeCPUOvercommit"):
        assert annotations[name]["rancher_url"] == EXPLORER
    for name in ("KubePodNotReady", "KubePodCrashLooping"):
        assert (
            annotations[name]["rancher_url"]
            == EXPLORER + "/pod/{{ $labels.namespace }}/{{ $labels.pod }}"
        )
    for name in ("KubeNodeNotReady", "KubeNodeUnreachable"):
        assert annotations[name]["rancher_url"] == EXPLORER + "/node/{{ $labels.node }}"

    assert values["kubeApiServer"]["serviceMonitor"]["relabelings"][0] == {
        "sourceLabels": ["__address__"],
        "action": "keep",
        "regex": r"10\.250\.0\.(1|3|41):6443",
    }
    assert values["kubelet"]["serviceMonitor"]["metricRelabelings"][0] == {
        "sourceLabels": ["instance", "__name__"],
        "action": "drop",
        "regex": (
            r"(192\.168\.0\.(23|24)|10\.250\.0\.5):10250;"
            r"(apiserver|etcd|scheduler|workqueue|kubeproxy)_.*"
        ),
    }


def test_transit_worker_fence_message_keeps_exact_value() -> None:
    """The native-fence assertion reports the full enrollment refusal text."""
    path = ROOT / "ansible/playbooks/k3s-transit-worker.yml"
    [play] = yaml.safe_load(path.read_text(encoding="utf-8"))
    [guard] = [
        task["ansible.builtin.assert"]
        for task in play["pre_tasks"]
        if "ansible.builtin.assert" in task
    ]
    assert guard["that"] == "not native_fence.stat.exists"
    assert guard["fail_msg"] == (
        "Native gateway is fenced. Use the explicit, reviewed rollback "
        "instead of worker enrollment."
    )
