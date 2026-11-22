"""Offline contracts for the peer15 endpoint relay replacement."""

import ast
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "peer15_endpoint", ROOT / "scripts/wg-peer15-endpoint.py"
)
endpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(endpoint)


class EndpointTests(unittest.TestCase):
    """Synthetic config checks and the static relay service contract."""

    def config(self) -> str:
        return (
            "[Interface]\nPrivateKey = SYNTHETIC-NOT-A-KEY\nListenPort = 51830\n\n"
            "[Peer]\nPublicKey = other-peer\nEndpoint = 127.0.0.1:51840\n\n"
            "[Peer]\n# socrat-1\nPublicKey = " + str(endpoint.PEER) + "\n"
            "AllowedIPs = 10.250.0.3/32, 10.42.1.0/24\n"
            "Endpoint = " + str(endpoint.DIRECT) + "\nPersistentKeepalive = 25\n\n"
            "[Peer]\nPublicKey = another-peer\nEndpoint = example.test:1234\n"
        )

    def test_only_one_endpoint_changed(self) -> None:
        """Replacing the direct endpoint is reversible and touches no other byte."""
        before = self.config()
        after = endpoint.replace_endpoint(before, endpoint.RELAY)
        assert after == before.replace(endpoint.DIRECT, endpoint.RELAY)
        assert endpoint.replace_endpoint(after, endpoint.DIRECT) == before

    def test_idempotent(self) -> None:
        """Applying the relay endpoint twice leaves the replaced config unchanged."""
        once = endpoint.replace_endpoint(self.config(), endpoint.RELAY)
        assert endpoint.replace_endpoint(once, endpoint.RELAY) == once

    def test_unknown_endpoint_rejected(self) -> None:
        """An endpoint outside the direct and relay pair is rejected."""
        with self.assertRaises(ValueError):
            endpoint.replace_endpoint(
                self.config().replace(endpoint.DIRECT, "192.0.2.1:1234"), endpoint.RELAY
            )

    def test_duplicate_peer_rejected(self) -> None:
        """Two copies of the peer block are rejected."""
        with self.assertRaises(ValueError):
            endpoint.replace_endpoint(self.config() + self.config(), endpoint.RELAY)

    def test_missing_peer_rejected(self) -> None:
        """A config without the peer1 key is rejected."""
        with self.assertRaises(ValueError):
            endpoint.replace_endpoint(
                self.config().replace(endpoint.PEER, "absent"), endpoint.RELAY
            )

    def test_duplicate_endpoint_rejected(self) -> None:
        """Two endpoint lines in the peer block are rejected."""
        with self.assertRaises(ValueError):
            endpoint.replace_endpoint(
                self.config().replace(
                    "Endpoint = " + endpoint.DIRECT,
                    "Endpoint = " + endpoint.DIRECT + "\nEndpoint = " + endpoint.DIRECT,
                ),
                endpoint.RELAY,
            )

    def test_service_has_no_keys_or_privileged_capabilities(self) -> None:
        """The relay unit has no key material and no privileged capabilities."""
        service = (ROOT / "ansible/files/wg-peer15-relay.service").read_text()
        for required in [
            "DynamicUser=yes",
            "NoNewPrivileges=yes",
            "CapabilityBoundingSet=\n",
            "IPAddressDeny=any",
            "IPAddressAllow=10.250.0.41/32 192.168.0.24/32",
        ]:
            assert required in service
        assert "PrivateKey" not in service
        relay = (ROOT / "ansible/scripts/wg-peer15-relay.py").read_text()
        tree = ast.parse(relay)
        expected = {
            "FRONT": ("10.250.0.1", 51835),
            "CLIENT": ("10.250.0.41", 51830),
            "BACK": ("192.168.0.23", 51836),
            "TARGET": ("192.168.0.24", 51830),
        }
        constants = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in expected
        }
        assert constants == expected
        assert any(
            isinstance(part, ast.Compare)
            and isinstance(part.left, ast.Name)
            and part.left.id == "source"
            and len(part.ops) == 1
            and isinstance(part.ops[0], ast.NotEq)
            and len(part.comparators) == 1
            and isinstance(part.comparators[0], ast.Name)
            and part.comparators[0].id == "CLIENT"
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            for part in ast.walk(node.test)
        )
        assert "0.0.0.0" not in relay


if __name__ == "__main__":
    unittest.main()
