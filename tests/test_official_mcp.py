import importlib.util
import json
import os
from pathlib import Path
import stat
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_real_project_config_has_no_inline_credentials_and_blocks_pending_clients():
    config=json.loads((ROOT/'.pi/mcp.json').read_text())['mcpServers']
    assert set(config)=={'socrat-grafana','argocd','socrat-metrics','n8n','umami','github'}
    for name in ('n8n','umami','github'):assert config[name]['enabled'] is False
    assert config['n8n']['exposure']=='hidden'
    assert set(config['n8n']['toolExposure'])=={'search_workflows','get_workflow_details'}
    for c in config.values():
        for value in c.get('headers',{}).values():assert value.startswith('!python3 scripts/mcp-credential.py ')
    assert config['socrat-grafana']['url'].endswith('/mcp')
    assert '/.pi/mcp.json' not in (ROOT/'.gitignore').read_text().splitlines()

def test_all_49_applications_are_audited_with_reason():
    audit=json.loads((ROOT/'deploy/mcp/service-audit.json').read_text())
    declared={p.stem for p in (ROOT/'deploy/argocd/apps').glob('*.yaml')}|{'root'}
    assert {r['application'] for r in audit['applications']}==declared
    assert all(r['decision'] and r['reason'] for r in audit['applications'])
    assert len(audit['workloads'])>=100
    assert set(audit['hostRunningUnits'])=={'socrat-0','socrat-1','socrat-2','socrat-3'}

def test_official_launchers_pin_read_only_and_do_not_override_tool_allowlist(monkeypatch):
    m=module('run-official-mcp');monkeypatch.setattr(m.creds,'read_private',lambda p:'unit-test-token')
    args,env=m.command('argocd');assert env['MCP_READ_ONLY']=='true';assert 'stdio' in args
    args,env=m.command('metrics')
    assert '--mcp.tools=build_info' in args
    assert not any(a.startswith('--prometheus.backend') for a in args)
    assert '--web.listen-address=127.0.0.1:0' in args
    assert any('datasources/proxy/uid/prometheus' in a for a in args)
    assert '--mcp.tools=all' not in args
    with pytest.raises(ValueError):m.command('unknown')

def test_secret_reader_rejects_symlink_and_unsafe_mode(tmp_path):
    m=module('mcp-credential');p=tmp_path/'key';p.write_text('unit-test-token');p.chmod(0o600)
    assert m.read_private(p)=='unit-test-token'
    p.chmod(0o644)
    with pytest.raises(ValueError):m.read_private(p)
    p.chmod(0o600);link=tmp_path/'link';link.symlink_to(p)
    with pytest.raises(OSError):m.read_private(link)
    p.write_text('bad\nmultiple\nlines')
    with pytest.raises(ValueError):m.read_private(p)

def test_package_lock_and_release_checksums_are_pinned():
    p=json.loads((ROOT/'tools/official-mcp/package.json').read_text())
    assert p['dependencies']=={'argocd-mcp':'0.9.0','@umami/mcp':'0.2.0'}
    lock=json.loads((ROOT/'tools/official-mcp/package-lock.json').read_text())
    assert lock['packages']['']['dependencies']==p['dependencies']
    assert all(v.get('integrity') for k,v in lock['packages'].items() if k.startswith('node_modules/'))
    m=module('setup-official-mcp');assert m.VERSION=='0.18.0'
    assert all(len(v[1])==64 for v in m.ARTIFACTS.values())

def test_native_n8n_mcp_is_exact_service_owned_without_bypassing_ui():
    docs=list(yaml.safe_load_all((ROOT/'charts/n8n/templates/access.yaml').read_text()))
    ui,machine=docs
    assert ui['metadata']['namespace']=='identity'
    assert ui['spec']['rules'][0]['http']['paths'][0]['backend']['service']['name']=='authentik-server'
    paths=machine['spec']['rules'][0]['http']['paths']
    mcp=[p for p in paths if p['path']=='/mcp-server/http'];assert len(mcp)==1 and mcp[0]['pathType']=='Exact'
    assert mcp[0]['backend']['service']['name']=='n8n'
    assert not any(p['path']=='/rest' for p in paths)
    assert not (ROOT/'deploy/identity/n8n-gateway.yaml').exists()

def test_grafana_remains_viewer_read_only_with_telemetry_and_cost_limits():
    text=(ROOT/'charts/grafana-mcp/templates/deployment.yaml').read_text()
    assert '--disable-write' in text
    assert '--enabled-tools=search,datasource,prometheus,alerting,dashboard,folder,navigation,loki,tempo,pyroscope' in text
    assert '--loki-guardrail-mode=enforce' in text
    assert '--loki-guardrail-max-bytes=536870912' in text
    assert '--allow-grafana-url-override=false' in text
    assert '--allow-cross-origin-redirects=false' in text
