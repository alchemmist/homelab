import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError


SOURCE = Path(__file__).resolve().parents[1] / "ansible/roles/monitoring_vpn/files/collect_vpn.py"
SPEC = importlib.util.spec_from_file_location("collect_vpn", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

HTTP_TIMEOUT = object()


def counters_payload(users):
    body = json.dumps({
        "cmdline": ["xray"],
        "memstats": {},
        "stats": {"user": users},
    }).encode()
    return io.BytesIO(body)


class PeerParsingTests(unittest.TestCase):
    def test_ipv6_mapped_ipv4_peer_is_dotted(self):
        line = "0 0 [::ffff:176.98.185.59]:32063 [::ffff:91.78.10.210]:51414"
        self.assertEqual(MODULE.peer_host(line), "91.78.10.210")

    def test_native_ipv4_peer(self):
        line = "0 0 10.250.0.2:32087 31.173.86.226:25560"
        self.assertEqual(MODULE.peer_host(line), "31.173.86.226")

    def test_state_prefix_is_tolerated(self):
        line = "ESTAB 0 0 [::ffff:176.98.185.59]:32083 [::ffff:31.173.86.226]:25560"
        self.assertEqual(MODULE.peer_host(line), "31.173.86.226")

    def test_private_ranges_are_filtered(self):
        for host in ("10.250.0.1", "192.168.0.23", "127.0.0.1", "172.17.0.2",
                     "fe80::1", "::1"):
            self.assertTrue(MODULE.is_private(host), host)
        for host in ("109.173.40.247", "176.98.185.59", "91.78.10.210", "172.32.0.1"):
            self.assertFalse(MODULE.is_private(host), host)


class StreamCountTests(unittest.TestCase):
    def test_streams_from_mixed_output(self):
        stdout = (
            "0 0 [::ffff:176.98.185.59]:32063 [::ffff:91.78.10.210]:51414\n"
            "0 0 [::ffff:176.98.185.59]:32063 [::ffff:91.78.10.210]:51415\n"
            "0 0 [::ffff:10.250.0.2]:32083 [::ffff:80.251.125.77]:40001\n"
            "0 0 [::ffff:176.98.185.59]:32053 [::ffff:10.250.0.1]:40002\n"
            "0 0 [::ffff:10.250.0.2]:32087 [::ffff:109.173.40.247]:40003\n"
        )
        result = subprocess.CompletedProcess([], 0, stdout=stdout)
        with patch.object(MODULE.subprocess, "run", return_value=result):
            self.assertEqual(MODULE.observe_streams([32087, 32053, 32083, 32063]), 5)

    def test_no_streams_is_zero(self):
        with patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="")):
            self.assertEqual(MODULE.observe_streams([32087]), 0)

    def test_all_ports_are_passed_to_ss_filter(self):
        with patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="")) as run:
            MODULE.observe_streams([32087, 32053])
        self.assertEqual(
            run.call_args[0][0][:6],
            ["ss", "-H", "-t", "state", "established", "( sport = :32087 or sport = :32053 )"],
        )


class XrayCountersTests(unittest.TestCase):
    def test_counters_sums_uplink_and_downlink_per_email(self):
        payload = counters_payload({"mom": {"downlink": 100, "uplink": 5},
                                    "tim": {"downlink": 7, "uplink": 50}})
        with patch.object(MODULE.urllib.request, "urlopen", return_value=payload) as urlopen:
            counters = MODULE.read_xray_user_counters("http://x/debug/vars", HTTP_TIMEOUT)
        self.assertEqual(counters, {"mom": 105, "tim": 57})
        urlopen.assert_called_once_with("http://x/debug/vars", timeout=HTTP_TIMEOUT)

    def test_malformed_payload_raises(self):
        for body in (b'{"memstats": {}}', b'[]', b'not json'):
            with patch.object(MODULE.urllib.request, "urlopen", return_value=io.BytesIO(body)):
                with self.assertRaises((KeyError, TypeError, ValueError)):
                    MODULE.read_xray_user_counters("http://x", HTTP_TIMEOUT)


class ActiveUsersTests(unittest.TestCase):
    def test_growth_marks_user_active_within_window(self):
        state = {"counters": {"mom": 100, "tim": 50},
                 "last_active": {"mom": 10.0, "tim": 900.0}}
        counters = {"mom": 100, "tim": 75}
        users = MODULE.active_users(counters, state, now=1000.0, window=60)
        self.assertEqual(users, ["tim"])
        self.assertEqual(state["last_active"]["tim"], 1000.0)
        self.assertEqual(state["counters"], counters)

    def test_silent_user_expires_after_window(self):
        state = {"counters": {"mom": 100}, "last_active": {"mom": 100.0}}
        users = MODULE.active_users({"mom": 100}, state, now=1000.0, window=60)
        self.assertEqual(users, [])

    def test_removed_accounts_are_pruned(self):
        state = {"counters": {"mom": 100, "gone": 5},
                 "last_active": {"mom": 900.0, "gone": 900.0}}
        users = MODULE.active_users({"mom": 130}, state, now=1000.0, window=60)
        self.assertEqual(users, ["mom"])
        self.assertNotIn("gone", state["last_active"])
        self.assertNotIn("gone", state["counters"])

    def test_counter_reset_after_xray_restart_is_not_activity(self):
        state = {"counters": {"mom": 500}, "last_active": {}}
        users = MODULE.active_users({"mom": 10}, state, now=1000.0, window=60)
        self.assertEqual(users, [])


class CollectorTests(unittest.TestCase):
    def collect_run(self):
        return MODULE.collect(
            ports=[32087, 32053, 32083, 32063],
            metrics_url="http://127.0.0.1:11112/debug/vars",
            metrics_timeout=5,
            window=60,
            output=str(self.output),
            state_path=str(self.state),
        )

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.output = Path(self.directory.name) / "vpn.prom"
        self.state = Path(self.directory.name) / "vpn.state.json"

    def tearDown(self):
        self.directory.cleanup()

    def test_registered_clients_read_from_xui_db(self):
        path = Path(self.directory.name) / "x-ui.db"
        connection = sqlite3.connect(path)
        connection.execute("create table inbounds (settings text)")
        docs = [
            json.dumps({"clients": [{"email": "a@x", "enable": True},
                                    {"email": "dup@x", "enable": True}]}),
            json.dumps({"clients": [{"email": "dup@x", "enable": True},
                                    {"email": "off@x", "enable": False},
                                    {"email": "b@x"}]}),
            "not json",
        ]
        for doc in docs:
            connection.execute("insert into inbounds values (?)", (doc,))
        connection.commit()
        connection.close()
        self.assertEqual(MODULE.read_registered_clients(str(path)), 3)
        self.assertIsNone(MODULE.read_registered_clients("/nonexistent/nope.db"))

    def test_registered_clients_metric_exported(self):
        output = self.directory.name + '/metrics.prom'
        MODULE.write_metrics(output, 3, ['a@x', 'b@x'], True, registered=7)
        self.assertIn('socrat_vpn_registered_clients 7', open(output).read())

    def test_full_success_cycle_across_runs(self):
        ss = subprocess.CompletedProcess([], 0, stdout="line1\nline2\n")
        payload = counters_payload({"mom": {"downlink": 100, "uplink": 5}})
        with patch.object(MODULE.subprocess, "run", return_value=ss), \
             patch.object(MODULE.urllib.request, "urlopen", return_value=payload):
            self.assertEqual(self.collect_run(), 0)
        text = self.output.read_text()
        self.assertIn("socrat_vpn_trojan_connections 2", text)
        # the first sample only records a baseline; nobody is proven active yet
        self.assertIn("socrat_vpn_active_clients 0", text)
        self.assertIn("socrat_vpn_collection_success 1", text)
        self.assertTrue(self.state.exists())

        # counters grow: mom transfers traffic; two more accounts appear active
        payload2 = counters_payload({"mom": {"downlink": 220, "uplink": 5},
                                     "tim": {"downlink": 0, "uplink": 9},
                                     "tv": {"downlink": 0, "uplink": 0}})
        with patch.object(MODULE.subprocess, "run", return_value=ss), \
             patch.object(MODULE.urllib.request, "urlopen", return_value=payload2):
            self.assertEqual(self.collect_run(), 0)
        text = self.output.read_text()
        # mom keeps transferring and keeps counting; tim is a new account so
        # this sample only baselines his counters
        self.assertIn("socrat_vpn_active_clients 1", text)
        self.assertIn('socrat_vpn_client_active{email="mom"} 1', text)
        self.assertNotIn('email="tim"', text)
        self.assertNotIn('email="tv"', text)

        # on the third run tim also transfers traffic; tv stays totally idle
        payload3 = counters_payload({"mom": {"downlink": 220, "uplink": 5},
                                     "tim": {"downlink": 0, "uplink": 9},
                                     "tv": {"downlink": 0, "uplink": 0}})
        payload3 = counters_payload({"mom": {"downlink": 220, "uplink": 5},
                                    "tim": {"downlink": 3, "uplink": 9},
                                    "tv": {"downlink": 0, "uplink": 0}})
        with patch.object(MODULE.subprocess, "run", return_value=ss), \
             patch.object(MODULE.urllib.request, "urlopen", return_value=payload3):
            self.assertEqual(self.collect_run(), 0)
        text = self.output.read_text()
        self.assertIn("socrat_vpn_active_clients 2", text)
        self.assertIn('socrat_vpn_client_active{email="mom"} 1', text)
        self.assertIn('socrat_vpn_client_active{email="tim"} 1', text)
        self.assertNotIn('email="tv"', text)
        self.assertNotIn('email="tv', '@unused@')

    def test_failure_replaces_previous_values_with_failed_collection(self):
        with patch.object(MODULE.subprocess, "run", side_effect=subprocess.TimeoutExpired("ss", 10)):
            self.assertEqual(self.collect_run(), 1)
        text = self.output.read_text()
        self.assertIn("socrat_vpn_collection_success 0", text)
        self.assertIn("socrat_vpn_trojan_connections 0", text)
        self.assertIn("socrat_vpn_active_clients 0", text)
        self.assertIn("socrat_vpn_collection_timestamp_seconds 0", text)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o644)
        leftovers = [p.name for p in Path(self.directory.name).iterdir()
                     if p.name.startswith('.')]
        self.assertEqual(sorted(leftovers), [])

    def test_expvar_outage_is_a_failed_collection(self):
        ss = subprocess.CompletedProcess([], 0, stdout="")
        with patch.object(MODULE.subprocess, "run", return_value=ss), \
             patch.object(MODULE.urllib.request, "urlopen", side_effect=URLError("down")):
            self.assertEqual(self.collect_run(), 1)
        self.assertIn("socrat_vpn_collection_success 0", self.output.read_text())

    def test_state_corruption_recovered_from_clean_slate(self):
        self.state.write_text("{ not json")
        ss = subprocess.CompletedProcess([], 0, stdout="")
        payload = counters_payload({"mom": {"downlink": 100, "uplink": 0}})
        with patch.object(MODULE.subprocess, "run", return_value=ss), \
             patch.object(MODULE.urllib.request, "urlopen", return_value=payload):
            self.assertEqual(self.collect_run(), 0)
        # fresh state only baselines the counters: success, but no activity yet
        self.assertIn("socrat_vpn_active_clients 0", self.output.read_text())
        self.assertIn("socrat_vpn_collection_success 1", self.output.read_text())
        self.assertEqual(json.loads(self.state.read_text())["counters"], {"mom": 100})


    def test_collector_interval_is_five_seconds(self):
        import importlib.util as _ilu
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / 'ansible/roles/monitoring_vpn/defaults/main.yml'
        self.assertIn('monitoring_vpn_interval: 5s', path.read_text())

if __name__ == "__main__":
    unittest.main()

class FallbackMetricTests(unittest.TestCase):
    def test_fallback_latch_is_exported_even_when_collection_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "active"
            output = Path(directory) / "vpn.prom"
            for active in (False, True):
                if active:
                    marker.touch()
                MODULE.write_metrics(str(output), 0, [], False, fallback_marker=str(marker))
                self.assertIn(f"socrat_vpn_fallback_active {int(active)}\n", output.read_text())
