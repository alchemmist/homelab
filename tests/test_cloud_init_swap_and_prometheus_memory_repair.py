"""Guards for two scoped repairs; no cluster or root access in tests."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLOUD = load('cloud-init-swap-repair')
PROM = load('prometheus-memory-repair')
SWAPS = 'Filename Type Size Used Priority\n/swap.img file 524284 26412 -2\n'
FSTAB = '/swap.img none swap sw 0 0\n'


def test_swap_repair_accepts_existing_persistent_active_swap():
    CLOUD.validate({'bootcmd': CLOUD.EXPECTED}, [{}, {'hostname': 'socrat-4'}],
                   SWAPS, FSTAB * 2, 512 * 1024 * 1024)


@pytest.mark.parametrize('change', ['provider', 'competitor', 'inactive', 'fstab', 'size'])
def test_swap_repair_refuses_unknown_conditions(change):
    base, others, swaps, fstab, size = {'bootcmd': CLOUD.EXPECTED}, [], SWAPS, FSTAB, 512 * 1024 * 1024
    if change == 'provider':
        base = {'bootcmd': ['another command']}
    if change == 'competitor':
        others = [{'bootcmd': []}]
    if change == 'inactive':
        swaps = SWAPS.splitlines()[0]
    if change == 'fstab':
        fstab = '/swap.img none swap discard 0 0'
    if change == 'size':
        size = 1
    with pytest.raises(RuntimeError):
        CLOUD.validate(base, others, swaps, fstab, size)


def test_cloud_atomic_permissions_and_no_active_swap_mutation(tmp_path):
    target = tmp_path / 'receipt'
    CLOUD.atomic(target, CLOUD.OVERRIDE, 0o600)
    assert target.read_text() == CLOUD.OVERRIDE
    assert target.stat().st_mode & 0o777 == 0o600
    source = (ROOT / 'scripts/cloud-init-swap-repair.py').read_text()
    assert "['cloud-init', 'single', '--name', 'bootcmd', '--frequency', 'always']" in source
    assert source.index("require(result.returncode == 0") < source.index("command(['systemctl', 'reset-failed'")
    assert "'swapoff'" not in source and "'mkswap'," not in source
    assert "'cloud-init', 'clean'" not in source


def expression():
    return '''[
        {
          "ownerPattern": dyn(''' + json.dumps(PROM.PATTERN) + '''),
          "containers": dyn({
            "prometheus": {
              "requests": dyn({"cpu": "200m", "memory": "2048Mi", "ephemeral-storage": "64Mi"}),
              "limits": dyn({"memory": "3072Mi", "ephemeral-storage": "1Gi"}),
              "removeCpuLimit": dyn(true)
            },
            "other": {"limits": dyn({"memory": "3072Mi"})}
          })
        },
        {
          "ownerPattern": dyn("unrelated"),
          "containers": dyn({"other": {"memory": "2048Mi"}})
        }
      ]'''


@pytest.mark.parametrize('indent', [0, 6, 12])
def test_only_prometheus_memory_scalars_change(indent):
    before = '\n'.join(line[indent:] if line.startswith(' ' * indent) else line
                       for line in expression().split('\n'))
    after = PROM.expression_change(before)
    expected = before.replace('"requests": dyn({"cpu": "200m", "memory": "2048Mi"',
                              '"requests": dyn({"cpu": "200m", "memory": "3072Mi"', 1)
    expected = expected.replace('"limits": dyn({"memory": "3072Mi", "ephemeral-storage": "1Gi"',
                                '"limits": dyn({"memory": "8192Mi", "ephemeral-storage": "1Gi"', 1)
    assert after == expected
    assert '"cpu": "200m"' in after
    assert '"other": {"limits": dyn({"memory": "3072Mi"})}' in after
    assert '"other": {"memory": "2048Mi"}' in after


@pytest.mark.parametrize('expr', [expression().replace('2048Mi', '1024Mi'),
                                  expression().replace('3072Mi', '6Gi'),
                                  expression() * 2, '[]'])
def test_policy_drift_refused(expr):
    with pytest.raises(RuntimeError):
        PROM.expression_change(expr)


def test_policy_cas_and_input_immutability():
    before = {'metadata': {'uid': 'policy-uid', 'resourceVersion': '42'},
              'spec': {'variables': [{'name': 'unrelated', 'expression': 'true'},
                                     {'name': 'profiles', 'expression': expression()}]}}
    original = copy.deepcopy(before)
    patch = PROM.policy_patch(before)
    assert before == original
    assert [p['op'] for p in patch] == ['test', 'test', 'test', 'replace']
    assert patch[1]['value'] == '42'
    assert patch[-1]['path'] == '/spec/variables/1/expression'


def pod():
    return {'metadata': {'name': PROM.NAME, 'namespace': PROM.NS, 'uid': 'pod-uid',
                         'resourceVersion': '24', 'ownerReferences': [
                             {'controller': True, 'kind': 'StatefulSet', 'name': PROM.STS}]},
            'spec': {'nodeName': 'socrat-0', 'containers': [
                {'name': 'other', 'resources': {}},
                {'name': 'prometheus', 'resources': {
                    'requests': {'cpu': '200m', 'memory': '2Gi'},
                    'limits': {'memory': '3Gi', 'ephemeral-storage': '1Gi'}}}]}}


def test_resize_only_ram_and_has_uid_rv_and_resource_guards():
    before = pod()
    original = copy.deepcopy(before)
    patch = PROM.resize_patch(before)
    assert before == original
    assert [p['op'] for p in patch] == ['test', 'test', 'test', 'replace', 'replace']
    assert [p['path'] for p in patch[-2:]] == [
        '/spec/containers/1/resources/requests/memory', '/spec/containers/1/resources/limits/memory']
    assert [p['value'] for p in patch[-2:]] == ['3Gi', '8Gi']


@pytest.mark.parametrize('change', ['node', 'controller', 'restart', 'memory', 'name'])
def test_resize_refuses_unknown_or_disruptive_conditions(change):
    value = pod()
    if change == 'node':
        value['spec']['nodeName'] = 'socrat-1'
    if change == 'controller':
        value['metadata']['ownerReferences'][0]['name'] = 'foreign'
    if change == 'restart':
        value['spec']['containers'][1]['resizePolicy'] = [
            {'resourceName': 'memory', 'restartPolicy': 'RestartContainer'}]
    if change == 'memory':
        value['spec']['containers'][1]['resources']['limits']['memory'] = '4Gi'
    if change == 'name':
        value['metadata']['name'] = 'foreign'
    with pytest.raises(RuntimeError):
        PROM.resize_patch(value)


def test_capacity_gate_includes_request_growth_and_ignores_failed_pods():
    value = pod()
    value['status'] = {'phase': 'Running'}
    dead = copy.deepcopy(value)
    dead['status']['phase'] = 'Failed'
    dead['spec']['containers'][1]['resources']['requests']['memory'] = '100Gi'
    result = PROM.memory_capacity({'status': {'allocatable': {'memory': '4Gi'}}}, [value, dead])
    assert result['current_requests_bytes'] == 2 * 1024 ** 3
    assert result['projected_remaining_bytes'] == 1024 ** 3


def test_capacity_gate_stops_before_mutation_if_request_growth_does_not_fit():
    with pytest.raises(RuntimeError, match='Insufficient node reservation'):
        PROM.memory_capacity({'status': {'allocatable': {'memory': '2500Mi'}}}, [pod()])
