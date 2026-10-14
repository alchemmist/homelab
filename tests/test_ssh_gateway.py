import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'ansible/roles/ssh_gateway/files/homelab_ssh_gateway.py'
SPEC = importlib.util.spec_from_file_location('ssh_gateway', SOURCE)
GATEWAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATEWAY)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / 'state.json'
        self.state_patch = patch.object(GATEWAY, 'STATE', self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.config = {
            'router_description': 'http://192.168.0.1:52869/picsdesc.xml',
            'external_address': '203.0.113.1',
            'gateway_address': '192.168.0.23',
            'nodes': [{'name': 'socrat-0', 'address': '192.168.0.23',
                       'external_port': 2222, 'ports': [2222, 22]}],
        }

    def response(self, output):
        return subprocess.CompletedProcess([], 0, output, '')

    def listing(self, entry=''):
        return self.response('ExternalIPAddress = 203.0.113.1\n' + entry)

    def test_existing_mapping_is_unchanged_and_recorded_when_router_rewrites_description(self):
        output = self.listing(" 4 TCP 2222->192.168.0.23:2222 'miniupnpd' '' 0\n")
        with patch.object(GATEWAY, 'ssh_port', return_value=2222), patch.object(GATEWAY.subprocess, 'run', return_value=output) as run:
            GATEWAY.reconcile(self.config)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(json.loads(self.state.read_text()), {'2222': ['192.168.0.23', 2222]})

    def test_missing_mapping_is_restored(self):
        responses = [self.listing(), self.response('external 203.0.113.1:2222 TCP is redirected to internal 192.168.0.23:2222')]
        with patch.object(GATEWAY, 'ssh_port', return_value=2222), patch.object(GATEWAY.subprocess, 'run', side_effect=responses) as run:
            GATEWAY.reconcile(self.config)
        self.assertIn('-a', run.call_args_list[1].args[0])
        self.assertEqual(json.loads(self.state.read_text())['2222'], ['192.168.0.23', 2222])

    def test_foreign_mapping_is_not_deleted(self):
        output = self.listing(" 4 TCP 2222->192.168.0.99:22 'another-service' '' 0\n")
        with patch.object(GATEWAY, 'ssh_port', return_value=2222), patch.object(GATEWAY.subprocess, 'run', return_value=output) as run:
            with self.assertRaisesRegex(RuntimeError, 'unmanaged'):
                GATEWAY.reconcile(self.config)
        self.assertEqual(run.call_count, 1)

    def test_backend_port_change_uses_persisted_ownership(self):
        self.state.write_text(json.dumps({'2222': ['192.168.0.23', 22]}))
        responses = [self.listing(" 4 TCP 2222->192.168.0.23:22 'miniupnpd' '' 0\n"),
                     self.response('deleted'),
                     self.response('external 203.0.113.1:2222 TCP is redirected to internal 192.168.0.23:2222')]
        with patch.object(GATEWAY, 'ssh_port', return_value=2222), patch.object(GATEWAY.subprocess, 'run', side_effect=responses) as run:
            GATEWAY.reconcile(self.config)
        self.assertIn('-d', run.call_args_list[1].args[0])
        self.assertEqual(json.loads(self.state.read_text())['2222'], ['192.168.0.23', 2222])

    def test_timeout_restores_previous_owned_mapping(self):
        self.state.write_text(json.dumps({'2222': ['192.168.0.23', 22]}))
        responses = [self.listing(" 4 TCP 2222->192.168.0.23:22 'miniupnpd' '' 0\n"),
                     self.response('deleted'), subprocess.TimeoutExpired('upnpc', 15),
                     self.response('restored')]
        with patch.object(GATEWAY, 'ssh_port', return_value=2222), patch.object(GATEWAY.subprocess, 'run', side_effect=responses) as run:
            with self.assertRaises(RuntimeError):
                GATEWAY.reconcile(self.config)
        self.assertEqual(run.call_args_list[3].args[0][-6:], ['-a', '192.168.0.23', '22', '2222', 'TCP', '0'])
        self.assertEqual(json.loads(self.state.read_text())['2222'], ['192.168.0.23', 22])

    def test_remote_node_maps_to_gateway_socket(self):
        self.config['nodes'] = [{'name': 'socrat-2', 'address': '10.250.0.2',
                                 'external_port': 2224, 'ports': [2222, 22], 'relay': True}]
        responses = [self.listing(), self.response('external 203.0.113.1:2224 TCP is redirected to internal 192.168.0.23:2224')]
        with patch.object(GATEWAY, 'ssh_port', return_value=22), patch.object(GATEWAY.subprocess, 'run', side_effect=responses):
            GATEWAY.reconcile(self.config)
        self.assertEqual(json.loads(self.state.read_text())['2224'], ['192.168.0.23', 2224])


if __name__ == '__main__':
    unittest.main()
