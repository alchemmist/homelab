from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[1]


def test_vllm_chart_and_authoritative_admission_agree():
    catalog = yaml.safe_load((ROOT / 'ansible/vars/container-resources.yml').read_text())
    profiles = catalog['container_resource_policy_profiles']
    matches = [p for p in profiles if p['namespace'] == 'llm' and p['ownerPattern'] == '^vllm-[a-z0-9]+$']
    assert len(matches) == 1
    budget = matches[0]['containers']['vllm']
    assert budget['requests']['memory'] == '10240Mi'
    assert budget['limits']['memory'] == '24576Mi'
    for name in ['charts/vllm/values.yaml', 'deploy/vllm/profiles/qwen3.8-27b.yaml']:
        values = yaml.safe_load((ROOT / name).read_text())
        assert values['resources']['requests']['memory'] == '10Gi'
        assert values['resources']['limits']['memory'] == '24Gi'


def test_worker_private_vip_route_is_narrow_and_preserves_admin_mesh():
    values = yaml.safe_load((ROOT / 'ansible/inventory/host_vars/socrat-3.yml').read_text())
    peers = values['wg_socrat_extra_allowed_peer_ips']['socrat-3']
    assert peers['socrat-0'] == ['192.168.0.23/32', '10.250.0.4/32', '192.168.0.250/32']
    assert peers['socrat-1'] == ['192.168.0.24/32']
    assert values['wg_socrat_admin_clients'] == {}
