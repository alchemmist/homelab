import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('otel_preflight', ROOT / 'scripts/otel-migration-preflight.py')
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)
GIB = 1024 ** 3


def fixtures():
    policy = json.loads((ROOT / 'deploy/monitoring/otel-migration-policy.json').read_text())
    for key in ('diskProjectionVerified', 'backupVerified', 'historyRoundtripVerified', 'historySourceIntegrityVerified', 'sourceRegistryVerified'):
        policy[key] = True
    inventory = {
        'schemaVersion': 1,
        'nodes': {node: {
            'hostname': node, 'observedAt': 1000, 'diskTotalBytes': 1000 * GIB,
            'diskAvailableBytes': 500 * GIB, 'memoryAvailableBytes': 16 * GIB,
        } for node in policy['nodes']},
        'targets': [{'health': 'up'}], 'prometheus': [{'version': 'v3.15.0'}],
    }
    return policy, inventory


class MigrationPreflightTests(unittest.TestCase):
    def test_ready_with_verified_prerequisites_and_capacity(self):
        policy, inventory = fixtures()
        self.assertTrue(PREFLIGHT.evaluate(policy, inventory, now=1000)['readyForCutover'])

    def test_default_policy_never_authorizes_cutover(self):
        _, inventory = fixtures()
        policy = json.loads(PREFLIGHT.DEFAULT_POLICY.read_text())
        result = PREFLIGHT.evaluate(policy, inventory, now=1000)
        self.assertFalse(result['readyForCutover'])
        self.assertEqual(len([error for error in result['errors'] if 'prerequisite' in error]), 4)

    def test_source_corruption_cannot_be_hidden_by_old_roundtrip_success(self):
        for mode in ('missing', 'false'):
            policy, inventory = fixtures()
            if mode == 'missing':
                del policy['historySourceIntegrityVerified']
            else:
                policy['historySourceIntegrityVerified'] = False
            result = PREFLIGHT.evaluate(policy, inventory, now=1000)
            self.assertFalse(result['readyForCutover'])
            self.assertIn('Unverified prerequisite: historySourceIntegrityVerified', result['errors'])

    def test_integrity_gate_links_to_the_unrepaired_source_incident(self):
        policy = json.loads(PREFLIGHT.DEFAULT_POLICY.read_text())
        self.assertFalse(policy['historySourceIntegrityVerified'])
        evidence = json.loads((ROOT / policy['historySourceIntegrityEvidence']).read_text())
        self.assertFalse(evidence['sourceIntegrityVerified'])
        self.assertEqual(evidence['badChunkCount'], 1)
        self.assertFalse(evidence['productionHistoryModified'])
        self.assertFalse(evidence['checksumChecksBypassed'])

    def test_backup_assertion_has_a_verified_receipt(self):
        policy = json.loads(PREFLIGHT.DEFAULT_POLICY.read_text())
        self.assertTrue(policy['backupVerified'])
        receipt = json.loads((ROOT / policy['backupEvidence']).read_text())
        self.assertTrue(receipt['verified'])
        self.assertTrue(receipt['snapshotIncludesHead'])
        self.assertTrue(receipt['controllerStateRestored'])
        self.assertFalse(receipt['originalsDeleted'])
        self.assertEqual(receipt['replicaHost'], 'socrat-3')
        self.assertEqual(len(receipt['archiveSha256']), 4)
        self.assertGreater(receipt['reports']['prometheus-snapshot.tar.gz']['blockCount'], 0)

    def test_missing_node_and_unhealthy_target_fail(self):
        policy, inventory = fixtures()
        del inventory['nodes']['socrat-2']
        inventory['targets'][0]['health'] = 'down'
        self.assertEqual(len(PREFLIGHT.evaluate(policy, inventory, now=1000)['errors']), 2)

    def test_disk_peak_uses_stricter_reserve(self):
        policy, inventory = fixtures()
        policy['nodes']['socrat-0']['projectedAdditionalDiskBytes'] = 301 * GIB
        result = PREFLIGHT.evaluate(policy, inventory, now=1000)
        self.assertTrue(any('disk space' in error for error in result['errors']))

    def test_known_memory_pressure_blocks_new_stack(self):
        policy, inventory = fixtures()
        inventory['nodes']['socrat-1']['memoryAvailableBytes'] = 4 * GIB
        result = PREFLIGHT.evaluate(policy, inventory, now=1000)
        self.assertTrue(any('socrat-1: insufficient' in error for error in result['errors']))

    def test_cluster_collectors_move_without_reducing_budgets(self):
        policy, inventory = fixtures()
        zero = policy['nodes']['socrat-0']['components']
        one = policy['nodes']['socrat-1']['components']
        self.assertEqual(zero, {
            'agent': 256 * 1024 ** 2,
            'clusterCollector': GIB,
            'traceGateway': GIB,
            'hostNodeExporter': 64 * 1024 ** 2,
        })
        self.assertEqual(one, {'agent': 256 * 1024 ** 2, 'loki': 2 * GIB, 'tempo': 2 * GIB, 'hostNodeExporter': 64 * 1024 ** 2})
        inventory['nodes']['socrat-1']['memoryAvailableBytes'] = 5 * GIB
        result = PREFLIGHT.evaluate(policy, inventory, now=1000)
        self.assertTrue(result['readyForCutover'])
        self.assertEqual(result['capacity']['socrat-0']['memoryRequiredBytes'], 2880 * 1024 ** 2)
        self.assertEqual(result['capacity']['socrat-1']['memoryRequiredBytes'], 4928 * 1024 ** 2)

    def test_relocated_collectors_still_require_memory_on_socrat_0(self):
        policy, inventory = fixtures()
        inventory['nodes']['socrat-0']['memoryAvailableBytes'] = 2 * GIB
        result = PREFLIGHT.evaluate(policy, inventory, now=1000)
        self.assertTrue(any('socrat-0: insufficient' in error for error in result['errors']))

    def test_stale_future_and_hostname_mismatch_fail(self):
        for updates in ({'observedAt': 1}, {'observedAt': 2000}, {'hostname': 'unexpected'}):
            policy, inventory = fixtures()
            inventory['nodes']['socrat-0'].update(updates)
            self.assertFalse(PREFLIGHT.evaluate(policy, inventory, now=1000)['readyForCutover'])

    def test_invalid_capacity_fails_closed(self):
        for invalid in (-1, float('nan'), float('inf'), True, '1000', None):
            policy, inventory = fixtures()
            inventory['nodes']['socrat-0']['memoryAvailableBytes'] = invalid
            self.assertFalse(PREFLIGHT.evaluate(policy, inventory, now=1000)['readyForCutover'])

    def test_negative_budget_is_rejected(self):
        policy, inventory = fixtures()
        policy['nodes']['socrat-1']['components']['tempo'] = -1
        with self.assertRaises(ValueError):
            PREFLIGHT.evaluate(policy, inventory, now=1000)

    def test_empty_and_old_inventory_fail(self):
        policy, inventory = fixtures()
        inventory['targets'] = []
        inventory['prometheus'] = []
        self.assertFalse(PREFLIGHT.evaluate(policy, inventory, now=1000)['readyForCutover'])
        inventory['schemaVersion'] = 0
        with self.assertRaises(ValueError):
            PREFLIGHT.evaluate(policy, inventory, now=1000)

    def test_evaluate_does_not_change_inputs(self):
        policy, inventory = fixtures()
        before = copy.deepcopy((policy, inventory))
        PREFLIGHT.evaluate(policy, inventory, now=1000)
        self.assertEqual((policy, inventory), before)

    def test_inventory_files_are_private_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inventory.json'
            PREFLIGHT.save(path, {'test': 1})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                PREFLIGHT.save(path, {'test': 2})
            self.assertEqual(json.loads(path.read_text()), {'test': 1})

    def test_monitor_inventory_does_not_export_credentials(self):
        monitor = {'kind': 'ServiceMonitor', 'metadata': {'namespace': 'monitoring', 'name': 'test'},
                   'spec': {'endpoints': [{'interval': '5s', 'authorization': {'credentials': {'name': 'private-token'}}}]}}
        result = PREFLIGHT.monitor_summary({'items': [monitor]})
        self.assertTrue(result[0]['requiresAuthentication'])
        self.assertNotIn('private-token', json.dumps(result))

    def test_contract_preserves_archive_and_tv_defaults(self):
        contract = json.loads(PREFLIGHT.DEFAULT_POLICY.read_text())['contract']
        self.assertFalse(contract['replaceProductionHistory'])
        self.assertFalse(contract['modifyCascadePolicy'])
        self.assertEqual(contract['historicalDownsampled'], 'native-thanos-preserved')
        self.assertEqual(contract['dashboardRefresh'], '5s')


if __name__ == '__main__':
    unittest.main()
