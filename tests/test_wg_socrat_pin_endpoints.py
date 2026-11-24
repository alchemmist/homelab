"""Pinned wg-socrat endpoints are restored after roaming."""

import importlib.util
import unittest
from pathlib import Path

PATH = (
    Path(__file__).resolve().parents[1]
    / "ansible/roles/wireguard_socrat/files/wg-socrat-pin-endpoints.py"
)


def load():
    spec = importlib.util.spec_from_file_location("wg_socrat_pin_endpoints", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONFIG = """\
[Interface]
Address = 10.250.0.1/24
[Peer]
PublicKey = node1=
AllowedIPs = 10.250.0.3/32
Endpoint = 192.168.0.24:51830
[Peer]
PublicKey = phone=
AllowedIPs = 10.250.0.4/32
"""


class PinEndpointTests(unittest.TestCase):
    def test_only_peers_with_endpoint_are_pinned(self):
        pin = load()
        self.assertEqual(pin.configured_endpoints(CONFIG), {"node1=": "192.168.0.24:51830"})

    def test_roam_into_tunnel_address_is_a_drift(self):
        pin = load()
        wanted = pin.configured_endpoints(CONFIG)
        runtime = pin.runtime_endpoints("node1=\t10.250.0.3:51830\nphone=\t1.2.3.4:9\n")
        self.assertEqual(
            pin.drifts(wanted, runtime),
            [("node1=", "192.168.0.24:51830", "10.250.0.3:51830")],
        )

    def test_matching_runtime_is_left_alone(self):
        pin = load()
        wanted = pin.configured_endpoints(CONFIG)
        runtime = pin.runtime_endpoints("node1=\t192.168.0.24:51830\n")
        self.assertEqual(pin.drifts(wanted, runtime), [])


if __name__ == "__main__":
    unittest.main()
