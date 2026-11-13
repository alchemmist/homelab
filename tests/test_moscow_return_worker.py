"""Owner requires Moscow membership; preserve fallback fences and bounded return."""
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]

def test_worker_desired_and_no_runtime_reinstallation():
    values=yaml.safe_load((ROOT/'charts/vpn-transit/values.yaml').read_text())
    assert values['replicas']==1
    assert values['nodeName']=='socrat-4'
    source=(ROOT/'ansible/playbooks/moscow-return-worker.yml').read_text()
    yaml.safe_load(source)
    assert 'default("preflight")' in source
    assert 'moscow_return_confirmed | default(false)' in source
    assert "mode == 'native-primary'" in source
    assert 'item.stat.checksum == item.item.sha' in source
    assert 'spec.replicas == 1' in source
    assert 'client-kubelet.crt' in source and 'meta.db' in source
    assert 'ExecCondition=/usr/bin/test ! -e' in source
    assert 'ExecCondition=+/usr/bin/test -e' in source
    assert source.index(' }} demote') < source.index('enabled: true') < source.index(' }} failback')
    assert 'async: 300' in source
    assert "mode == 'kubernetes'" in source
    for forbidden in ['k3s-agent-uninstall', 'iptables -F', 'kubectl delete', 'systemctl start k3s-agent', 'rm -rf']:
        assert forbidden not in source
