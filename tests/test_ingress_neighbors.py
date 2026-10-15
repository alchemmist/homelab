import importlib.util
import json
from pathlib import Path
import socket
import struct
import subprocess
import unittest
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / 'ansible/roles/home_ingress_ha/files/announce_neighbors.py'
SPEC = importlib.util.spec_from_file_location('ingress_neighbors', MODULE_PATH)
NEIGHBORS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NEIGHBORS)


def config():
    return {'interface': 'wlan0', 'address': '192.168.0.24', 'vip': '192.168.0.250', 'neighbors': [{'address': '192.168.0.1', 'mac': '02:11:22:33:44:55'}, {'address': '192.168.0.23', 'mac': '10:7c:61:08:33:76'}]}


def state(vip=False):
    addresses = ['192.168.0.24'] + (['192.168.0.250'] if vip else [])
    return {'ifname': 'wlan0', 'address': '38:d5:7a:e6:01:8b', 'addr_info': [{'family': 'inet', 'local': address} for address in addresses]}


class IngressNeighborsTest(unittest.TestCase):
    def setUp(self):
        packet_family = patch.object(NEIGHBORS.socket, 'AF_PACKET', 17, create=True)
        packet_family.start()
        self.addCleanup(packet_family.stop)

    def test_wire_format_is_directed_ethernet_arp_request(self):
        frame = NEIGHBORS.frames_for_interface(config(), state())[0]
        self.assertEqual(len(frame), 42)
        self.assertEqual(frame[:6], bytes.fromhex('021122334455'))
        self.assertEqual(frame[6:12], bytes.fromhex('38d57ae6018b'))
        self.assertEqual(struct.unpack('!HHHBBH', frame[12:22]), (0x0806, 1, 0x0800, 6, 4, 1))
        self.assertEqual(frame[22:28], frame[6:12])
        self.assertEqual(socket.inet_ntoa(frame[28:32]), '192.168.0.24')
        self.assertEqual(frame[32:38], frame[:6])
        self.assertEqual(socket.inet_ntoa(frame[38:42]), '192.168.0.1')

    def test_backup_announces_only_physical_address_to_both_neighbors(self):
        frames = NEIGHBORS.frames_for_interface(config(), state())
        self.assertEqual([socket.inet_ntoa(frame[28:32]) for frame in frames], ['192.168.0.24'] * 2)
        self.assertEqual([socket.inet_ntoa(frame[38:42]) for frame in frames], ['192.168.0.1', '192.168.0.23'])

    def test_owner_also_announces_vip_to_both_neighbors(self):
        frames = NEIGHBORS.frames_for_interface(config(), state(vip=True))
        self.assertEqual([socket.inet_ntoa(frame[28:32]) for frame in frames], ['192.168.0.24'] * 2 + ['192.168.0.250'] * 2)

    def test_physical_address_must_exist_before_any_socket_is_opened(self):
        missing = state(vip=True)
        missing['addr_info'] = missing['addr_info'][1:]
        with patch.object(NEIGHBORS, 'read_interface', return_value=missing), patch.object(NEIGHBORS.socket, 'socket') as factory:
            with self.assertRaises(ValueError):
                NEIGHBORS.announce(config())
            factory.assert_not_called()

    def test_invalid_configuration_is_rejected_before_interface_query(self):
        variants = []
        for field, value in [('interface', '../wlan0'), ('interface', '-wlan0'), ('interface', 'x' * 16), ('address', '::1'), ('address', '224.0.0.1'), ('vip', '0.0.0.0'), ('neighbors', [])]:
            item = config()
            item[field] = value
            variants.append(item)
        for mac in ['ff:ff:ff:ff:ff:ff', '01:00:5e:00:00:01', '00:00:00:00:00:00', 'invalid']:
            item = config()
            item['neighbors'][1]['mac'] = mac
            variants.append(item)
        for item in variants:
            with self.subTest(config=item), patch.object(NEIGHBORS, 'read_interface') as query:
                with self.assertRaises(ValueError):
                    NEIGHBORS.announce(item)
                query.assert_not_called()

    def test_invalid_local_mac_and_wrong_interface_are_rejected(self):
        for field, value in [('address', 'ff:ff:ff:ff:ff:ff'), ('address', None), ('ifname', 'eno1')]:
            item = state()
            item[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                NEIGHBORS.frames_for_interface(config(), item)

    def test_announcement_sends_once_without_waiting_for_replies(self):
        connection = Mock()
        connection.send.side_effect = lambda frame: len(frame)
        with patch.object(NEIGHBORS, 'read_interface', return_value=state(vip=True)), patch.object(NEIGHBORS.socket, 'socket') as factory:
            factory.return_value.__enter__.return_value = connection
            self.assertEqual(NEIGHBORS.announce(config()), 4)
            factory.assert_called_once_with(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0806))
        connection.bind.assert_called_once_with(('wlan0', 0))
        connection.settimeout.assert_called_once_with(1)
        self.assertEqual(connection.send.call_count, 4)
        connection.recv.assert_not_called()
        connection.recvfrom.assert_not_called()

    def test_interface_query_has_bounded_timeout_and_no_shell(self):
        with patch.object(NEIGHBORS.subprocess, 'run', return_value=Mock(stdout=json.dumps([state()]))) as run:
            self.assertEqual(NEIGHBORS.read_interface('wlan0'), state())
        run.assert_called_once_with(['ip', '-j', 'address', 'show', 'dev', 'wlan0'], check=True, capture_output=True, text=True, timeout=2)

    def test_failed_interface_query_prevents_transmission(self):
        with patch.object(NEIGHBORS.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ip', 2)), patch.object(NEIGHBORS.socket, 'socket') as factory:
            with self.assertRaises(subprocess.TimeoutExpired):
                NEIGHBORS.announce(config())
            factory.assert_not_called()

    def test_partial_frame_send_fails(self):
        with patch.object(NEIGHBORS, 'read_interface', return_value=state()), patch.object(NEIGHBORS.socket, 'socket') as factory:
            factory.return_value.__enter__.return_value.send.return_value = 1
            with self.assertRaises(OSError):
                NEIGHBORS.announce(config())


if __name__ == '__main__':
    unittest.main()
