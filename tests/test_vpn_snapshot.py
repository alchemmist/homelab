"""Offline contracts for VPN subscription identity and configuration snapshots."""

import base64
import importlib.util
import sqlite3
import unittest
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "verify_vpn",
    Path(__file__).resolve().parents[1] / "ansible/roles/vpn_consolidation/files/verify_vpn.py",
)
VPN = importlib.util.module_from_spec(SPEC)

DUPLICATE_LINK_COUNT = 2
SPEC.loader.exec_module(VPN)


class SubscriptionTests(unittest.TestCase):
    """Subscription normalization contracts for the offline VPN verifier."""

    def test_reality_short_id_rotation_keeps_identity(self) -> None:
        """Keep client identity when only the reality short id rotates."""
        first = b"vless://client@example.org:443?security=reality&sid=aaa&pbk=key#name"
        second = b"vless://client@example.org:443?pbk=key&sid=bbb&security=reality#name"
        assert VPN.normalize_subscription(first) == VPN.normalize_subscription(
            base64.b64encode(second)
        )
        assert VPN.normalize_subscription(first) != VPN.normalize_subscription(
            second.replace(b"client@", b"other@")
        )
        assert VPN.normalize_subscription(first) != VPN.normalize_subscription(
            second.replace(b"pbk=key", b"pbk=other")
        )

    def test_non_reality_sid_is_preserved(self) -> None:
        """Preserve a non-reality sid as part of the subscription identity."""
        first = b"vless://client@example.org:443?security=tls&sid=aaa"
        assert VPN.normalize_subscription(first) != VPN.normalize_subscription(
            first.replace(b"aaa", b"bbb")
        )

    def test_duplicate_links_remain_visible(self) -> None:
        """Count duplicate links instead of collapsing them."""
        link = b"vless://client@example.org:443?security=tls"
        assert len(VPN.normalize_subscription(link + b"\n" + link)) == DUPLICATE_LINK_COUNT

    def test_empty_and_invalid_payloads_fail(self) -> None:
        """Reject empty and non-subscription payloads."""
        for value in (
            b"",
            b"<html>not a subscription</html>",
            base64.b64encode(b"invalid"),
        ):
            with pytest.raises(ValueError):
                VPN.normalize_subscription(value)


class ConfigurationTests(unittest.TestCase):
    """SQLite configuration snapshot contracts for the offline VPN verifier."""

    def test_traffic_changes_ignored_but_quota_and_password_changes_detected(
        self,
    ) -> None:
        """Ignore traffic counters while detecting quota and password changes."""
        with sqlite3.connect(":memory:") as connection:
            for table in VPN.TABLES:
                if table == "inbounds":
                    connection.execute(
                        "CREATE TABLE inbounds (id INTEGER, up INTEGER, down INTEGER, total INTEGER, settings TEXT)"
                    )
                    connection.execute(
                        "INSERT INTO inbounds VALUES (1, 10, 20, 1000, 'client-identity')"
                    )
                elif table == "users":
                    connection.execute(
                        "CREATE TABLE users (id INTEGER, password TEXT, login_epoch INTEGER)"
                    )
                    connection.execute("INSERT INTO users VALUES (1, 'password', 0)")
                else:
                    connection.execute('CREATE TABLE "' + table + '" (id INTEGER)')
            expected = VPN.configuration(connection)
            connection.execute("UPDATE inbounds SET up=50, down=100")
            connection.execute("UPDATE users SET login_epoch=1")
            assert expected == VPN.configuration(connection)
            connection.execute("UPDATE inbounds SET total=2000")
            assert expected != VPN.configuration(connection)
            connection.execute("UPDATE inbounds SET total=1000")
            connection.execute("UPDATE users SET password='changed'")
            assert expected != VPN.configuration(connection)


if __name__ == "__main__":
    unittest.main()
