import importlib.util
from pathlib import Path

MODULE = Path("charts/monitoring-k3s/files/update_watch.py")


def load_module():
    spec = importlib.util.spec_from_file_location("update_watch", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_open_webui_style_gap_is_an_update():
    watch = load_module()
    releases = [
        {"tag_name": "v0.13.3", "draft": False, "prerelease": False},
        {"tag_name": "v0.13.4-rc.1", "draft": False, "prerelease": True},
        {"tag_name": "v0.12.3", "draft": False, "prerelease": False},
    ]
    latest, tag = watch.latest_stable(releases)
    assert tag == "v0.13.3"
    assert latest > watch.parse_version("v0.12.3-slim")


def test_equal_version_is_not_an_update():
    watch = load_module()

    def fetch(_repo, _timeout):
        return [{"tag_name": "v1.2.3", "draft": False, "prerelease": False}]

    samples = watch.evaluate(
        [{"id": "demo", "title": "Demo", "current": "1.2.3", "github": "acme/demo"}],
        fetch,
        1,
    )
    assert samples[0]["available"] == 0
    assert samples[0]["success"] == 1
    body = watch.render_metrics(samples)
    assert 'current="1.2.3"' in body and "} 0" in body


def test_failed_lookup_does_not_claim_an_update():
    watch = load_module()

    def fetch(_repo, _timeout):
        raise OSError("github unavailable")

    samples = watch.evaluate(
        [{"id": "demo", "title": "Demo", "current": "1.2.3", "github": "acme/demo"}],
        fetch,
        1,
    )
    assert samples[0]["available"] == 0
    assert samples[0]["success"] == 0


def test_catalog_lists_open_webui():
    text = Path("charts/monitoring-k3s/values.yaml").read_text()
    assert "github: open-webui/open-webui" in text
    assert 'current: "0.12.3"' in text


def test_statefulset_target_and_ambiguous_workload():
    import pytest
    watch=load_module()
    assert watch.workload_ref({'statefulset':'openhands'}) == ('statefulsets','openhands')
    assert watch.workload_ref({'deployment':'open-webui'}) == ('deployments','open-webui')
    with pytest.raises(ValueError):
        watch.workload_ref({'deployment':'a','statefulset':'b'})


def test_openhands_uses_running_canvas_tag_not_sdk_version():
    import yaml
    watch=load_module()
    catalog=yaml.safe_load(Path('charts/monitoring-k3s/values.yaml').read_text())['updateWatch']['targets']
    target=next(x for x in catalog if x['id']=='openhands')
    assert target['github']=='OpenHands/OpenHands'
    assert target['statefulset']=='openhands'
    assert target['namespace']=='openhands'
    assert target['container']=='agent-canvas'
    samples=watch.evaluate([target],lambda repo,t:[{'tag_name':'v1.42.0'}],1,{'openhands':'ghcr.io/openhands/agent-canvas:1.41.0@sha256:fixture'})
    assert samples[0]['current']=='1.41.0'
    assert samples[0]['latest']=='1.42.0'
    assert samples[0]['available']==1
    assert samples[0]['success']==1
