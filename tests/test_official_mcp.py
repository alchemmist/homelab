"""Offline checks for pinned official MCP config, launchers, and chart ownership."""

import importlib.util
import json
import subprocess
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def module(name: str) -> types.ModuleType:
    """Test behavior for module."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_optional_pi_example_has_no_inline_credentials_and_blocks_pending_clients() -> None:
    """Require disabled pending clients and command-backed credential headers."""
    config = json.loads((ROOT / "deploy/mcp/examples/pi-mcp.json").read_text())["mcpServers"]
    assert set(config) == {
        "socrat-grafana",
        "argocd",
        "socrat-metrics",
        "n8n",
        "umami",
        "github",
    }
    for name in ("n8n", "umami", "github"):
        assert config[name]["enabled"] is False
    assert config["n8n"]["exposure"] == "hidden"
    assert set(config["n8n"]["toolExposure"]) == {
        "search_workflows",
        "get_workflow_details",
    }
    for c in config.values():
        for value in c.get("headers", {}).values():
            assert value.startswith("!python3 scripts/mcp-credential.py ")
    assert config["socrat-grafana"]["url"].endswith("/mcp")
    assert "/.pi/" in (ROOT / ".gitignore").read_text().splitlines()


def test_pi_opt_in_only_writes_ignored_private_config(tmp_path: Path) -> None:
    """No network, credentials, global Pi config, or project trust is needed for this test."""
    setup = module("setup-official-mcp")
    project = tmp_path / "checkout"
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    runtime = tmp_path / "runtime"
    private = tmp_path / "private"
    with pytest.raises(ValueError, match="unignored"):
        setup.configure_project_files(project, target=runtime, folder=private)
    assert not (project / ".pi").exists()
    (project / ".gitignore").write_text("/.pi/\n")
    setup.configure_project_files(project, target=runtime, folder=private)
    local = project / ".pi/mcp.json"
    servers = json.loads(local.read_text())["mcpServers"]
    assert servers["argocd"]["args"][0] == str(runtime / "bin/run-official-mcp.py")
    assert servers["n8n"]["enabled"] is False
    assert local.stat().st_mode & 0o777 == 0o600
    subprocess.run(["git", "-C", str(project), "add", "-f", ".pi/mcp.json"], check=True)
    with pytest.raises(ValueError, match="tracked"):
        setup.configure_project_files(project, target=runtime, folder=private)


def test_all_current_applications_are_audited_with_reason() -> None:
    """Require every current application audit row to carry a decision and reason."""
    audit = json.loads((ROOT / "deploy/mcp/service-audit.json").read_text())
    declared = {p.stem for p in (ROOT / "deploy/argocd/apps").glob("*.yaml")} | {"root"}
    assert {r["application"] for r in audit["applications"]} == declared
    assert all(r["decision"] and r["reason"] for r in audit["applications"])
    assert len(audit["workloads"]) >= 100
    assert set(audit["hostRunningUnits"]) == {
        "socrat-0",
        "socrat-1",
        "socrat-2",
        "socrat-3",
    }


def test_official_launchers_pin_read_only_and_do_not_override_tool_allowlist(
    monkeypatch,
) -> None:
    """Pin read-only launcher args and reject an unknown server name."""
    m = module("run-official-mcp")
    monkeypatch.setattr(m.creds, "read_private", lambda p: "unit-test-token")
    args, env = m.command("argocd")
    assert env["MCP_READ_ONLY"] == "true"
    assert "stdio" in args
    args, env = m.command("metrics")
    assert "--mcp.tools=build_info" in args
    assert not any(a.startswith("--prometheus.backend") for a in args)
    assert "--web.listen-address=127.0.0.1:0" in args
    assert any("datasources/proxy/uid/prometheus" in a for a in args)
    assert "--mcp.tools=all" not in args
    with pytest.raises(ValueError):
        m.command("unknown")


def test_secret_reader_rejects_symlink_and_unsafe_mode(tmp_path) -> None:
    """Accept only a mode 0600 regular file and reject links or multiline text."""
    m = module("mcp-credential")
    p = tmp_path / "key"
    p.write_text("unit-test-token")
    p.chmod(0o600)
    assert m.read_private(p) == "unit-test-token"
    p.chmod(0o644)
    with pytest.raises(ValueError):
        m.read_private(p)
    p.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(p)
    with pytest.raises(OSError):
        m.read_private(link)
    p.write_text("bad\nmultiple\nlines")
    with pytest.raises(ValueError):
        m.read_private(p)


def test_package_lock_and_release_checksums_are_pinned() -> None:
    """Require pinned package versions and 64-character release checksums."""
    p = json.loads((ROOT / "deploy/mcp/clients/package.json").read_text())
    assert p["dependencies"] == {
        "@umami/mcp": "0.2.0",
        "argocd-mcp": "file:argocd-mcp-0.9.0-homelab.tar",
        "zod": "4.6.7",
    }
    lock = json.loads((ROOT / "deploy/mcp/clients/package-lock.json").read_text())
    assert lock["packages"][""]["dependencies"] == p["dependencies"]
    assert all(
        v.get("integrity") for k, v in lock["packages"].items() if k.startswith("node_modules/")
    )
    m = module("setup-official-mcp")
    assert m.VERSION == "0.18.0"
    assert all(len(v[1]) == 64 for v in m.ARTIFACTS.values())


def test_native_n8n_mcp_is_exact_service_owned_without_bypassing_ui() -> None:
    """Keep the native n8n UI and an exact machine MCP path on the same service."""
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/n8n.yaml").read_text())["spec"]
    helm = app["source"]["helm"]
    cmd = [
        "helm",
        "template",
        helm["releaseName"],
        str(ROOT / app["source"]["path"]),
        "-n",
        app["destination"]["namespace"],
    ]
    baseline = list(yaml.safe_load_all(subprocess.check_output(cmd, text=True)))
    for param in helm["parameters"]:
        cmd.extend(["--set", f"{param['name']}={param['value']}"])
    docs = list(yaml.safe_load_all(subprocess.check_output(cmd, text=True)))
    ingresses = {d["metadata"]["name"]: d for d in docs if d and d["kind"] == "Ingress"}
    assert set(ingresses) == {"n8n", "n8n-machine-endpoints"}
    for ingress in ingresses.values():
        assert ingress["metadata"].pop("labels") == {
            "homelab.alchemmist.xyz/public-web": "true"
        }
    assert docs == baseline
    machine = ingresses["n8n-machine-endpoints"]
    assert machine["metadata"]["name"] == "n8n-machine-endpoints"
    assert machine["metadata"]["namespace"] == "automation"
    # 57767f73 deliberately retired the external IdP proxy: UI is native n8n,
    # not an unauthenticated machine-route shortcut through the old outpost.
    ui = (ROOT / "charts/n8n/templates/ingress.yaml").read_text()
    assert "path: /" in ui
    assert "name: n8n" in ui
    assert "tls:" in ui
    assert "websecure" in ui
    assert (
        "N8N_SECURE_COOKIE"
        in (ROOT / "charts/n8n/templates/deployment.yaml").read_text()
    )
    paths = machine["spec"]["rules"][0]["http"]["paths"]
    mcp = [p for p in paths if p["path"] == "/mcp-server/http"]
    assert len(mcp) == 1
    assert mcp[0]["pathType"] == "Exact"
    assert mcp[0]["backend"]["service"]["name"] == "n8n"
    assert not any(p["path"] == "/rest" for p in paths)
    assert not (ROOT / "deploy/identity/n8n-gateway.yaml").exists()


def test_grafana_remains_viewer_read_only_with_telemetry_and_cost_limits() -> None:
    """Keep Grafana MCP write-disabled with the reviewed tool and guardrail pins."""
    text = (ROOT / "charts/grafana-mcp/templates/deployment.yaml").read_text()
    assert "--disable-write" in text
    assert (
        "--enabled-tools=search,datasource,prometheus,alerting,dashboard,folder,navigation,loki,tempo,pyroscope"
        in text
    )
    assert "--loki-guardrail-mode=enforce" in text
    assert "--loki-guardrail-max-bytes=536870912" in text
    assert "--allow-grafana-url-override=false" in text
    assert "--allow-cross-origin-redirects=false" in text
