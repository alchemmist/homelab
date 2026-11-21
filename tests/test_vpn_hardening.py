import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

XUI_PLAIN_INBOUND_PORT = 32063
FIXTURE_IDENTITY_COUNT = 2
BACKUP_FILE_MODE = 0o600
STATE_DIR_MODE = 0o700
EXPECTED_COUNTER_RULES = 12
RECEIVED_BYTES_SENTINEL = 40000


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inventory = load("inventory_test", "vpn-hardening-inventory.py")
audit = load("counter_test", "vpn-backend-audit.py")


class HardeningTests(unittest.TestCase):
    def fixture(self, path):
        con = sqlite3.connect(path)
        con.executescript("""
        CREATE TABLE inbounds(id INTEGER, port INTEGER, protocol TEXT, enable INTEGER,
          stream_settings TEXT, settings TEXT, up INTEGER, down INTEGER, last_traffic_reset_time INTEGER);
        CREATE TABLE clients(id INTEGER, secret TEXT);
        CREATE TABLE client_inbounds(client_id INTEGER, inbound_id INTEGER);
        CREATE TABLE hosts(id INTEGER, address TEXT, inbound_id INTEGER, is_disabled INTEGER);
        INSERT INTO clients VALUES(1,'PRIVATE_TEST_SENTINEL');
        INSERT INTO client_inbounds VALUES(1,1);
        INSERT INTO hosts VALUES(1,'192.0.2.1',1,0);
        """)
        stream = json.dumps(
            {
                "network": "xhttp",
                "security": "reality",
                "realitySettings": {
                    "target": "www.yahoo.com:443",
                    "serverNames": ["www.yahoo.com"],
                    "privateKey": "PRIVATE_TEST_SENTINEL",
                },
            }
        )
        con.execute(
            "INSERT INTO inbounds VALUES(1,32053,'vless',1,?,?,0,0,0)", (stream, '{"clients":[]}')
        )
        con.commit()
        return con

    def test_summary_contains_no_client_or_key_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "vpn.db"
            con = self.fixture(path)
            result = inventory.inspect(path)
            con.close()
            assert "PRIVATE_TEST_SENTINEL" not in json.dumps(result)
            assert result["identities"] == 1
            assert result["client_links"] == 1
            assert result["production_configuration_writes"] == 0

    def test_encrypted_alternative_counts_require_enabled_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "vpn.db"
            con = self.fixture(path)
            con.execute(
                "INSERT INTO inbounds VALUES(2,32063,'vless',1,?, ?,0,0,0)",
                ('{"network":"xhttp","security":"none"}', '{"clients":[]}'),
            )
            con.execute("INSERT INTO client_inbounds VALUES(1,2)")
            con.commit()
            result = inventory.inspect(path)
            plain = next(r for r in result["inbounds"] if r["port"] == XUI_PLAIN_INBOUND_PORT)
            assert plain["links_with_existing_enabled_encrypted_alternative"] == 1
            con.execute("UPDATE hosts SET is_disabled=1")
            con.commit()
            plain = next(
                r
                for r in inventory.inspect(path)["inbounds"]
                if r["port"] == XUI_PLAIN_INBOUND_PORT
            )
            assert plain["links_with_existing_enabled_encrypted_alternative"] == 0
            assert plain["device_compatibility_and_subscription_render_unproven"]
            con.close()

    def test_counters_do_not_change_hash_but_config_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "vpn.db"
            con = self.fixture(path)
            before = inventory.inspect(path)["configuration_sha256"]
            con.execute("UPDATE inbounds SET up=100, down=200,last_traffic_reset_time=300")
            con.commit()
            assert before == inventory.inspect(path)["configuration_sha256"]
            con.execute("UPDATE hosts SET address='192.0.2.2'")
            con.commit()
            assert before != inventory.inspect(path)["configuration_sha256"]
            con.close()

    def test_online_backup_includes_wal_and_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "vpn.db"
            con = self.fixture(path)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA wal_autocheckpoint=0")
            con.execute("INSERT INTO clients VALUES(2,'PRIVATE_WAL_SENTINEL')")
            con.commit()
            state = root / "state"
            result = inventory.inspect(path, state)
            assert result["identities"] == FIXTURE_IDENTITY_COUNT
            assert (state / "x-ui-before.sqlite3").stat().st_mode & 0o777 == BACKUP_FILE_MODE
            assert state.stat().st_mode & 0o777 == STATE_DIR_MODE
            with contextlib.closing(sqlite3.connect(state / "x-ui-before.sqlite3")) as backup:
                assert (
                    backup.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
                    == FIXTURE_IDENTITY_COUNT
                )
            with self.assertRaises(ValueError):
                inventory.inspect(path, state)
            con.close()

    def test_symlink_db_and_public_state_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "vpn.db"
            self.fixture(path).close()
            link = root / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                inventory.inspect(link)
            state = root / "state"
            state.mkdir(mode=0o755)
            state.chmod(0o755)
            with self.assertRaises(ValueError):
                inventory.inspect(path, state)

    def test_rules_only_count_two_ports(self):
        rules = audit.rules()
        assert "policy accept" in rules
        for forbidden in (
            " drop",
            " reject",
            "flush",
            "masquerade",
            "dnat",
            "snat",
            "log ",
            "18082",
            "32063",
            "32085",
            "32086",
            "2222",
            "443",
        ):
            assert forbidden not in rules
        assert rules.count(" counter comment ") == EXPECTED_COUNTER_RULES
        assert 'iifname "lo"' in rules
        assert "12096:other" in rules
        assert "32087:other" in rules

    def test_counter_and_handle_changes_do_not_invalidate_hash(self):
        left = [{"rule": {"handle": 1, "expr": [{"counter": {"packets": 1, "bytes": 20}}]}}]
        right = [{"rule": {"handle": 2, "expr": [{"counter": {"packets": 7, "bytes": 80}}]}}]
        assert audit.plan(left) == audit.plan(right)
        right[0]["rule"]["expr"].append({"drop": None})
        assert audit.plan(left) != audit.plan(right)

    def test_unowned_table_refused(self):
        payload = {
            "nftables": [
                {"table": {"family": "inet", "name": audit.TABLE, "comment": "someone else"}}
            ]
        }
        with patch.object(audit, "run", return_value=json.dumps(payload)):
            with self.assertRaises(ValueError):
                audit.read_table()

    def test_nft_106_missing_comment_requires_exact_policy(self):
        objects = audit.expected_objects()
        # nft 1.0.6 JSON has no table comment, and may reorder anonymous sets.
        objects[-1]["rule"]["expr"][0]["match"]["right"]["set"].reverse()
        objects[-1]["rule"]["expr"][-1]["counter"] = {"packets": 5, "bytes": 100}
        audit.validate_objects(objects)
        objects[-1]["rule"]["expr"].append({"drop": None})
        with self.assertRaises(ValueError):
            audit.validate_objects(objects)

    def test_readback_finalizes_without_any_remote_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp).resolve()
            (state / "lock").touch()
            approval = audit.helpers.digest(audit.plan(None))
            (state / "before.json").write_text("null")
            (state / "uncertain.json").write_text(json.dumps({"plan_sha256": approval}))
            with (
                patch.object(audit.socket, "gethostname", return_value="socrat-2"),
                patch.object(audit.os, "geteuid", return_value=0),
                patch.object(audit.helpers, "private_directory", return_value=state),
                patch.object(audit, "read_table", return_value=audit.expected_objects()),
                patch.object(audit, "run") as run,
            ):
                receipt = audit.finalize_readback(approval, state)
                run.assert_not_called()
                assert receipt["remote_writes"] == 0
                assert not (state / "uncertain.json").exists()

    def test_apply_refuses_wrong_host_and_bad_hash(self):
        with patch.object(audit.socket, "gethostname", return_value="socrat-0"):
            with self.assertRaises(ValueError):
                audit.apply("bad", None)
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp).resolve() / "state"
            with (
                patch.object(audit.socket, "gethostname", return_value="socrat-2"),
                patch.object(audit.os, "geteuid", return_value=os.geteuid()),
                patch.object(audit, "read_table", return_value=None),
                patch.object(audit, "run") as run,
            ):
                # Root is checked independently of the current CI uid.
                with (
                    patch.object(audit.os, "geteuid", return_value=0),
                    patch.object(audit.helpers, "private_directory", side_effect=lambda _: state),
                ):
                    state.mkdir(mode=0o700)
                    with self.assertRaises(ValueError):
                        audit.apply("wrong", state)
                    run.assert_not_called()

    def test_default_is_preview_and_render_is_offline(self):
        with (
            patch("sys.argv", ["audit", "--render"]),
            patch.object(audit, "run") as run,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            audit.main()
            run.assert_not_called()
            assert "policy accept" in output.getvalue()
        with (
            patch("sys.argv", ["audit"]),
            patch.object(audit, "read_table", return_value=None),
            patch.object(audit, "apply") as apply,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            audit.main()
            apply.assert_not_called()
            assert not json.loads(output.getvalue())["enforcement"]


class PathCheckTests(unittest.TestCase):
    def test_rejects_credentials_queries_and_unapproved_hosts(self):
        probe = load("path_check_test", "vpn-path-check.py")
        for url in (
            "http://wiki.socrat.alchemmist.xyz/",
            "https://user:secret@wiki.socrat.alchemmist.xyz/",
            "https://wiki.socrat.alchemmist.xyz/?token=secret",
            "https://example.com/",
            "https://vpn.alchemmist.xyz/sub/secret",
            "https://wiki.socrat.alchemmist.xyz:444/",
        ):
            with self.assertRaises(ValueError):
                probe.endpoint(url)

    def test_address_control_cannot_scan_arbitrary_destinations(self):
        probe = load("path_check_address", "vpn-path-check.py")
        with self.assertRaises(ValueError):
            probe.check(
                "https://wiki.socrat.alchemmist.xyz/", "control", control_address="192.0.2.1"
            )
        with self.assertRaises(ValueError):
            probe.check(
                "https://wiki.socrat.alchemmist.xyz/",
                "control",
                family=6,
                control_address="109.120.141.97",
            )

    def test_records_dns_failure_without_claiming_tunnel_or_recovery(self):
        probe = load("path_check_failure", "vpn-path-check.py")
        with patch.object(
            probe.socket, "getaddrinfo", side_effect=OSError("PRIVATE_TEST_SENTINEL")
        ):
            result = probe.check("https://wiki.socrat.alchemmist.xyz/", "external-control")
        assert result["first_failed_stage"] == "dns"
        assert not result["native_tunnel_test"]
        assert not result["automatic_recovery"]
        assert "PRIVATE_TEST_SENTINEL" not in json.dumps(result)

    def test_complete_large_transfer_and_incomplete_transfer_are_distinct(self):
        from unittest.mock import MagicMock

        probe = load("path_check_body", "vpn-path-check.py")
        for declared, expected in ((40000, True), (90000, False)):
            tls = MagicMock()
            tls.makefile.return_value = io.BytesIO(
                b"HTTP/1.1 200 OK\r\nContent-Length: "
                + str(declared).encode()
                + b"\r\n\r\n"
                + b"x" * 40000
            )
            tls.version.return_value = "TLSv1.3"
            tls.selected_alpn_protocol.return_value = "http/1.1"
            ctx = MagicMock()
            ctx.wrap_socket.return_value.__enter__.return_value = tls
            address = (probe.socket.AF_INET, probe.socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))
            with (
                patch.object(probe.socket, "getaddrinfo", return_value=[address]),
                patch.object(probe.socket, "socket"),
                patch.object(probe.ssl, "create_default_context", return_value=ctx),
            ):
                result = probe.check("https://wiki.socrat.alchemmist.xyz/", "test-network")
            assert result.get("complete_success_above_32k", False) == expected
            assert result["received_bytes"] == RECEIVED_BYTES_SENTINEL
            assert not result["native_tunnel_test"]


class RealityPlanTests(unittest.TestCase):
    def setup_plan(self):
        planner = load("reality_plan", "vpn-reality-plan.py")
        policy = json.loads((ROOT / "deploy/vpn-hardening/policy.json").read_text())
        config = {
            "inbounds": [
                {
                    "id": 1,
                    "port": 32053,
                    "protocol": "vless",
                    "enable": 1,
                    "stream_settings": json.dumps(
                        {
                            "network": "xhttp",
                            "security": "reality",
                            "realitySettings": {
                                "target": "www.intel.com:443",
                                "serverNames": ["www.yahoo.com"],
                                "privateKey": "PRIVATE_TEST_SENTINEL",
                                "shortIds": ["PRIVATE_TEST_SENTINEL"],
                            },
                        }
                    ),
                }
            ],
            "clients": [{"id": 1, "secret": "PRIVATE_TEST_SENTINEL"}],
            "client_inbounds": [],
            "hosts": [],
        }
        return planner, policy, config

    def test_preview_preserves_input_and_hides_client_material(self):
        planner, policy, config = self.setup_plan()
        before = json.dumps(config, sort_keys=True)
        result = planner.build(config, policy)
        assert json.dumps(config, sort_keys=True) == before
        assert len(result["operations"]) == 1
        assert result["operations"][0]["new"] == "www.yahoo.com:443"
        assert "PRIVATE_TEST_SENTINEL" not in json.dumps(result)
        assert result["production_writes"] == 0

    def test_already_correct_target_is_noop(self):
        planner, policy, config = self.setup_plan()
        stream = json.loads(config["inbounds"][0]["stream_settings"])
        stream["realitySettings"]["target"] = "www.yahoo.com:443"
        config["inbounds"][0]["stream_settings"] = json.dumps(stream)
        result = planner.build(config, policy)
        assert result["operations"] == []
        assert result["before_configuration_sha256"] == result["planned_configuration_sha256"]

    def test_sni_and_security_drift_stop(self):
        planner, policy, config = self.setup_plan()
        for field, value in (("security", "none"), ("network", "grpc")):
            changed = json.loads(json.dumps(config))
            stream = json.loads(changed["inbounds"][0]["stream_settings"])
            stream[field] = value
            changed["inbounds"][0]["stream_settings"] = json.dumps(stream)
            with self.assertRaises(ValueError):
                planner.build(changed, policy)
        stream = json.loads(config["inbounds"][0]["stream_settings"])
        stream["realitySettings"]["serverNames"] = ["www.sony.com"]
        config["inbounds"][0]["stream_settings"] = json.dumps(stream)
        with self.assertRaises(ValueError):
            planner.build(config, policy)

    def test_ambiguous_target_and_scope_changes_stop(self):
        planner, policy, config = self.setup_plan()
        stream = json.loads(config["inbounds"][0]["stream_settings"])
        stream["realitySettings"]["dest"] = "www.intel.com:443"
        config["inbounds"][0]["stream_settings"] = json.dumps(stream)
        with self.assertRaises(ValueError):
            planner.build(config, policy)
        policy["newVpsOrPublicIp"] = True
        with self.assertRaises(ValueError):
            planner.build(config, policy)
