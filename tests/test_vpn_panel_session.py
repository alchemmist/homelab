"""Tests for the VPN panel session management script."""

import hashlib
import importlib.util
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from typing import ClassVar, Protocol
from unittest.mock import patch

import pytest

from ci.quality.closed_root_backend import entries, plain, view, whole

ROOT = Path(__file__).resolve().parents[1]


def load_vpn_module(name: str, path: Path) -> types.ModuleType:
    """Load a deployed-by-copy VPN tool from its exact source path."""
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None or not module_spec.has_location:
        reason = "Cannot load deployed VPN module"
        raise ValueError(reason)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


EXPECTED_REMOVED_PLAINTEXT_LINKS = 7
EXPECTED_UPSTREAM_PORT = 443
SESSION_FILE_MODE = 0o600
EXPECTED_FAILURE_THRESHOLD = 4
LEGACY_ENDPOINT_COUNT = 2
m = load_vpn_module("panel_session", ROOT / "ci/vpn/vpn-panel-session.py")
TEMP_ROOT = Path(tempfile.gettempdir())


class NativeSessionHarness(Protocol):
    """Structural surface of the native panel session exercised by these tests."""

    names: dict[str, str]
    credentials: dict[str, dict[str, object]]

    def call(self, method: str, path: str, body: object = None) -> object: ...

    def owned(self, kind: str) -> object: ...

    def cleanup(self) -> None: ...


class SessionTests(unittest.TestCase):
    """Tests for SessionTests."""

    TOKEN_VALUES: ClassVar[dict[str, str]] = {
        "bootstrap": "B" * 48,
        "cleanup": "C" * 48,
        "worker": "W" * 48,
    }

    def private_directory(self, path: Path) -> Path:
        """Create the requested private state directory."""
        path.mkdir(mode=0o700)
        return path

    def pristine_token_row(self) -> dict[str, object]:
        """Return the single untouched original token row of the fake panel."""
        return {
            "id": 1,
            "name": "existing",
            "scope": "admin",
            "enabled": 1,
            "token": "untouched-hash",
            "created_at": 1,
            "expires_at": 0,
        }

    def exercise_session(self, s: NativeSessionHarness, rows: list[dict[str, object]]) -> None:
        """Drive worker calls, the ownership guard and both cleanups."""
        assert not any(r["name"] == s.names["bootstrap"] for r in rows)
        assert s.credentials["worker"]["scope"] == "node-sync"
        s.call("GET", "/inbounds/list")
        with pytest.raises(ValueError, match="cannot use administrative"):
            s.call("POST", "/setting/apiTokens/create", {})
        # Ownership mismatch must never delete a credential.
        worker = next(r for r in rows if r["name"] == s.names["worker"])
        old = worker["token"]
        forged_hash = "foreign"
        worker["token"] = forged_hash
        with pytest.raises(ValueError, match="ownership changed"):
            s.owned("worker")
        worker["token"] = old
        s.cleanup()
        s.cleanup()

    def test_unsafe_name_rejected(self) -> None:
        for name in ("install", "cli-fallback", "vpn83-../x", "vpn83-a"):
            with pytest.raises(ValueError, match="session name"):
                m.NativeSession(TEMP_ROOT / name)

    def test_collision_refuses_even_preview(self) -> None:
        s = m.NativeSession(TEMP_ROOT / "vpn83-20261108-test")
        with (
            patch.object(m, "token_rows", return_value=[{"name": s.names["worker"]}]),
            patch.object(m, "pod_identity") as pod,
        ):
            with pytest.raises(ValueError, match="collision"):
                s.preview()
            pod.assert_not_called()

    def test_api_paths_and_redirects_are_restricted(self) -> None:
        for path in ("/setting/reset", "/inbounds/update/1?x=y", "/../secret"):
            with pytest.raises(ValueError, match="Unreviewed native API operation"):
                m.request("http://127.0.0.1:18082/base", "A" * 48, "POST", path, {})
        with pytest.raises(ValueError, match="redirect refused"):
            m.NoRedirect().redirect_request(None, None, None, None, None, None)

    def test_wrong_host_refuses_before_token_creation(self) -> None:
        s = m.NativeSession(TEMP_ROOT / "vpn83-20261108-host")
        with (
            patch.object(m.socket, "gethostname", return_value="socrat-0"),
            patch.object(m.subprocess, "run") as run,
        ):
            with pytest.raises(ValueError, match="requires root"):
                s.open("bad")
            run.assert_not_called()

    def test_native_success_and_cleanup_preserve_original_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp).resolve() / "vpn83-20261108-success"
            s = m.NativeSession(state)
            original = self.pristine_token_row()
            rows: list[dict[str, object]] = [original.copy()]
            calls: list[tuple[str, str, str, object]] = []

            def insert(kind: str, scope: str, expires: int = 0) -> dict[str, object]:
                row = {
                    "id": max([whole(x["id"]) for x in rows]) + 1,
                    "name": s.names[kind],
                    "scope": scope,
                    "enabled": 1,
                    "expires_at": expires,
                    "created_at": 2,
                    "token": hashlib.sha256(self.TOKEN_VALUES[kind].encode()).hexdigest(),
                }
                rows.append(row)
                return {
                    "id": row["id"],
                    "name": row["name"],
                    "scope": scope,
                    "expiresAt": expires,
                    "token": self.TOKEN_VALUES[kind],
                }

            def cli(args: list[str], **kwargs: object) -> object:
                assert "-tokenName" in args
                assert s.names["bootstrap"] in args
                assert "existing" not in args
                insert("bootstrap", "admin")
                handle = kwargs["stdout"]
                if not isinstance(handle, io.TextIOBase):
                    reason = "expected the private bootstrap stdout handle"
                    raise TypeError(reason)
                handle.write("apiToken: " + self.TOKEN_VALUES["bootstrap"] + "\n")
                return type("Result", (), {"returncode": 0})()

            def api(base: str, token: str, method: str, path: str, body: object = None) -> object:
                assert base == "http://127.0.0.1:18082/base/panel/api"
                calls.append((token, method, path, body))
                if path.endswith("/create"):
                    payload = view(body)
                    kind = next(k for k in self.TOKEN_VALUES if s.names[k] == payload["name"])
                    assert whole(payload["expiresAt"]) > 0
                    return insert(kind, plain(payload["scope"]), whole(payload["expiresAt"]))
                if "/delete/" in path:
                    target = int(path.rsplit("/", 1)[1])
                    payload = view(body)
                    row = next(r for r in rows if r["id"] == target)
                    assert row["scope"] == payload["expectedScope"]
                    rows.remove(row)
                    return None
                assert token == self.TOKEN_VALUES["worker"]
                return []

            def directory(path: Path) -> Path:
                path.mkdir(mode=0o700)
                return path

            with (
                patch.object(m.socket, "gethostname", return_value="socrat-2"),
                patch.object(m.os, "geteuid", return_value=0),
                patch.object(m, "token_rows", side_effect=lambda *_: [x.copy() for x in rows]),
                patch.object(
                    m,
                    "pod_identity",
                    return_value={"name": "pod", "uid": "pinned", "image": m.IMAGE},
                ),
                patch.object(m.h, "inspect", return_value={"configuration_sha256": "cfg"}),
                patch.object(m.h, "private_directory", side_effect=directory),
                patch.object(m, "api_path", return_value="http://127.0.0.1:18082/base/panel/api"),
                patch.object(m.subprocess, "run", side_effect=cli),
                patch.object(m, "request", side_effect=api),
            ):
                approval = m.h.digest(s.preview())
                s.open(approval)
                self.exercise_session(s, rows)
            self.assert_pristine_cleanup(state, rows, original)

    def assert_pristine_cleanup(
        self, state: Path, rows: list[dict[str, object]], original: dict[str, object]
    ) -> None:
        """Assert the private cleanup evidence: untouched originals and no secrets."""
        assert rows == [original]
        assert json.loads((state / "credential-cleanup.json").read_text())[
            "existing_tokens_unchanged"
        ]
        assert not (state / "uncertain.json").exists()
        for filename in (
            "bootstrap.stdout",
            "bootstrap.json",
            "cleanup.json",
            "worker.json",
        ):
            assert not (state / filename).exists()
        assert "B" * 48 not in json.dumps(
            json.loads((state / "credential-cleanup.json").read_text())
        )

    def test_wrong_approval_does_not_invoke_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp).resolve() / "vpn83-20261108-approval"
            s = m.NativeSession(state)

            with (
                patch.object(m.socket, "gethostname", return_value="socrat-2"),
                patch.object(m.os, "geteuid", return_value=0),
                patch.object(m.h, "private_directory", side_effect=self.private_directory),
                patch.object(s, "preview", return_value={"x": 1}),
                patch.object(m.subprocess, "run") as run,
            ):
                with pytest.raises(ValueError, match="approval hash required"):
                    s.open("wrong")
                run.assert_not_called()
            if s.lock:
                s.lock.close()


class TargetHelperTests(unittest.TestCase):
    """Tests for TargetHelperTests."""

    def module(self) -> types.ModuleType:
        """Load the deployed Reality apply tool for direct helper testing."""
        return load_vpn_module("target_apply", ROOT / "ci/vpn/vpn-reality-apply.py")

    def inbound(self) -> dict[str, object]:
        stream = {
            "network": "xhttp",
            "security": "reality",
            "xhttpSettings": {"path": "/", "mode": "auto"},
            "realitySettings": {
                "target": "www.intel.com:443",
                "serverNames": ["www.yahoo.com"],
                "privateKey": "PRIVATE_SENTINEL",
                "shortIds": ["short-private"],
                "settings": {"publicKey": "public-only"},
            },
        }
        return {
            "id": 1,
            "port": 32053,
            "protocol": "vless",
            "enable": True,
            "streamSettings": json.dumps(stream),
            "settings": '{"clients":[{"id":"client-private","flow":""}]}',
            "clientStats": [{"secret": "sentinel"}],
        }

    def test_only_target_is_patched_and_stats_not_posted(self) -> None:
        module = self.module()
        before = self.inbound()
        after = module.api_payload(before)
        assert "clientStats" not in after
        assert after["settings"] == before["settings"]
        a = json.loads(plain(after["streamSettings"]))
        b = json.loads(plain(before["streamSettings"]))
        assert a["realitySettings"]["target"] == "www.yahoo.com:443"
        b["realitySettings"]["target"] = "www.yahoo.com:443"
        assert a == b
        assert (
            json.loads(plain(before["streamSettings"]))["realitySettings"]["target"]
            == "www.intel.com:443"
        )

    def test_unexpected_sni_or_security_stops(self) -> None:
        module = self.module()
        before = self.inbound()
        stream = json.loads(plain(before["streamSettings"]))
        stream["security"] = "none"
        before["streamSettings"] = json.dumps(stream)
        with pytest.raises(ValueError, match="Transport drift"):
            module.api_payload(before)

    def test_probe_is_loopback_and_only_allows_public_test_destination(self) -> None:
        module = self.module()
        cfg = module.vless_client(
            json.loads(plain(self.inbound()["streamSettings"])), "new-owned-id", 12345
        )
        assert cfg["inbounds"][0]["listen"] == "127.0.0.1"
        assert cfg["outbounds"][0]["protocol"] == "blackhole"
        assert cfg["routing"]["rules"][0]["domain"] == ["full:speed.cloudflare.com"]
        assert "PRIVATE_SENTINEL" not in json.dumps(cfg)
        assert cfg["outbounds"][1]["settings"]["vnext"][0]["users"][0]["flow"] == ""

    def test_json_formatting_is_not_a_semantic_change(self) -> None:
        module = self.module()
        a = {"inbounds": [{"id": 1, "stream_settings": '{"b":2,"a":1}'}]}
        b = {"inbounds": [{"id": 1, "stream_settings": '{ "a": 1, "b": 2 }'}]}
        assert module.semantic(a) == module.semantic(b)

    def test_modern_nested_json_dto_is_supported_without_legacy_reencoding(self) -> None:
        module = self.module()
        before = self.inbound()
        before["streamSettings"] = json.loads(plain(before["streamSettings"]))
        before["settings"] = json.loads(plain(before["settings"]))
        before["sniffing"] = None
        after = module.api_payload(before)
        assert isinstance(after["streamSettings"], dict)
        assert after["streamSettings"]["realitySettings"]["target"] == "www.yahoo.com:443"
        assert after["settings"] == before["settings"]
        after_stream = view(before["streamSettings"])
        assert view(after_stream["realitySettings"])["target"] == "www.intel.com:443"
        assert module.json_field(None) is None
        assert module.json_field("") is None


class SubscriptionMigrationTests(unittest.TestCase):
    """Tests for SubscriptionMigrationTests."""

    def module(self) -> types.ModuleType:
        """Load the deployed subscription migration tool."""
        return load_vpn_module("sub_migrate", ROOT / "ci/vpn/vpn-subscription-migrate.py")

    def test_payload_only_excludes_publication(self) -> None:
        m = self.module()
        before = {
            "id": 7,
            "port": 32063,
            "protocol": "vless",
            "enable": True,
            "excludeFromSub": False,
            "streamSettings": {"network": "xhttp", "security": "none"},
            "settings": {"clients": [{"id": "PRESERVE"}]},
            "clientStats": [],
        }
        after = m.payload(before, 7)
        assert after["enable"]
        assert after["excludeFromSub"]
        expected = dict(before, excludeFromSub=True)
        expected.pop("clientStats")
        assert after == expected
        assert not before["excludeFromSub"]
        with pytest.raises(ValueError, match="API preimage drift"):
            m.payload(after, 7)

    def test_publication_delta_preserves_opaque_imports_and_credentials(self) -> None:
        m = self.module()
        secure = "vless://preserved@192.0.2.1:32053?security=reality"
        legacy = "vless://preserved@192.0.2.1:32063?security=none"
        opaque = "vpn://opaque-private"
        before = {str(i): sorted([secure, legacy, opaque]) for i in range(7)}
        after = {k: sorted([secure, opaque]) for k in before}
        assert (
            m.check_delta(before, after)["plaintext_links_removed"]
            == EXPECTED_REMOVED_PLAINTEXT_LINKS
        )
        after["0"] = [secure]
        with pytest.raises(ValueError, match="Unexpected subscription change"):
            m.check_delta(before, after)

    def test_only_reality_random_id_is_normalized(self) -> None:
        m = self.module()
        before = {
            "shortId": "preserve",
            "streamSettings": {
                "realitySettings": {"shortId": "random", "publicKey": "preserve-key"}
            },
        }
        after = m.normalize_json(before)
        assert after == {
            "shortId": "preserve",
            "streamSettings": {"realitySettings": {"publicKey": "preserve-key"}},
        }
        assert view(view(before["streamSettings"])["realitySettings"])["shortId"] == "random"
        assert m.json_legacy(
            {"outbounds": [{"protocol": "vless", "settings": {"vnext": [{"port": 32063}]}}]}
        )
        assert not m.json_legacy(
            {"outbounds": [{"protocol": "trojan", "settings": {"vnext": [{"port": 32063}]}}]}
        )

    def test_native_flat_vless_json_settings_are_detected(self) -> None:
        m = self.module()
        assert m.json_legacy(
            {
                "outbounds": [
                    {
                        "protocol": "vless",
                        "settings": {
                            "address": "192.0.2.1",
                            "port": 32063,
                            "id": "PRESERVE",
                        },
                    }
                ]
            }
        )
        assert not m.json_legacy(
            {"outbounds": [{"protocol": "vless", "settings": {"port": 32053}}]}
        )


class BackendGuardTests(unittest.TestCase):
    """Tests for BackendGuardTests."""

    def module(self, filename: str) -> types.ModuleType:
        """Load the deployed backend guard or enforcement tool by file name."""
        return load_vpn_module("backend_test", ROOT / "ci/vpn" / filename)

    def test_exact_owned_guard_and_missing_table_comment_supported(self) -> None:
        m = self.module("vpn-backend-guard.py")
        objects = m.expected()
        m.validate(objects)
        objects[0]["table"]["comment"] = m.OWNER
        m.validate(objects)
        objects[-1]["rule"]["expr"][1]["match"]["right"]["set"].append(443)
        with pytest.raises(ValueError, match="exact owned backend guard"):
            m.validate(objects)

    def test_foreign_owner_and_extra_rule_refused(self) -> None:
        m = self.module("vpn-backend-guard.py")
        objects = m.expected()
        objects[0]["table"]["comment"] = "foreign"
        with pytest.raises(ValueError, match="Foreign table owner"):
            m.validate(objects)
        objects = m.expected()
        objects.append({"rule": {"expr": [{"accept": None}]}})
        with pytest.raises(ValueError, match="exact owned backend guard"):
            m.validate(objects)

    def test_exact_existing_netbird_allowance_preserved_without_relaxing_public_guard(
        self,
    ) -> None:
        import copy

        m = self.module("vpn-backend-guard.py")
        allow = {
            "rule": {
                "family": "inet",
                "table": m.TABLE,
                "chain": "input",
                "expr": [
                    {
                        "match": {
                            "op": "==",
                            "left": {"meta": {"key": "iifname"}},
                            "right": "nb-host",
                        }
                    },
                    {"counter": {"packets": 17, "bytes": 900}},
                    {"accept": None},
                ],
            }
        }
        objects = m.expected()
        objects.insert(2, allow)
        before = copy.deepcopy(objects)
        m.validate(objects)
        assert objects == before
        for iface in ["eth0", "lo", "wg-socrat"]:
            bad = copy.deepcopy(objects)
            bad[2]["rule"]["expr"][0]["match"]["right"] = iface
            with (
                self.subTest(interface=iface),
                pytest.raises(ValueError, match="exact owned backend guard"),
            ):
                m.validate(bad)
        bad = copy.deepcopy(objects)
        bad.append(copy.deepcopy(allow))
        with pytest.raises(ValueError, match="Duplicate private interface allowance"):
            m.validate(bad)
        bad = copy.deepcopy(objects)
        bad[2]["rule"]["expr"].append({"drop": None})
        with pytest.raises(ValueError, match="exact owned backend guard"):
            m.validate(bad)
        bad = copy.deepcopy(objects)
        bad[-1]["rule"]["expr"][-1] = {"accept": None}
        with pytest.raises(ValueError, match="exact owned backend guard"):
            m.validate(bad)

    def test_guard_scope_and_boot_ensure(self) -> None:
        m = self.module("vpn-backend-guard.py")
        text = m.rules()
        assert 'iifname "eth0"' in text
        assert "{ 12096, 32087 }" in text
        assert "ct state established" in text
        assert "flush" not in text
        assert "forward" not in text
        assert " log " not in text
        assert "--ensure" in m.UNIT
        assert "ExecStop=" not in m.UNIT

    def test_trojan_probe_uses_fresh_own_secret_and_verified_tls443(self) -> None:
        m = self.module("vpn-backend-enforce.py")
        cfg = m.client(
            {
                "network": "ws",
                "security": "none",
                "wsSettings": {"path": "/owned-test"},
            },
            "OWN_FRESH_SECRET",
            12345,
        )
        assert cfg["inbounds"][0]["listen"] == "127.0.0.1"
        proxy = cfg["outbounds"][1]
        assert proxy["settings"]["servers"][0]["port"] == EXPECTED_UPSTREAM_PORT
        assert not proxy["streamSettings"]["tlsSettings"]["allowInsecure"]
        assert cfg["outbounds"][0]["protocol"] == "blackhole"
        assert cfg["routing"]["rules"][0]["domain"] == ["full:speed.cloudflare.com"]

    def test_nft_106_conntrack_membership_uses_in_operator(self) -> None:
        m = self.module("vpn-backend-guard.py")
        expr = m.expected()[2]["rule"]["expr"][2]
        assert expr["match"]["op"] == "in"
        assert expr["match"]["right"] == "established"


class HomeProbeTests(unittest.TestCase):
    """Tests for HomeProbeTests."""

    def module(self) -> types.ModuleType:
        """Load the deployed home probe tool."""
        return load_vpn_module("home_probe", ROOT / "ci/vpn/vpn-home-probe.py")

    def test_home_receipt_write_is_private_exclusive(self) -> None:
        m = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "proof.json"
            m.exclusive(p, {"own_fixture": True})
            assert p.stat().st_mode & 0o777 == SESSION_FILE_MODE
            with pytest.raises(FileExistsError):
                m.exclusive(p, {"overwrite": True})

    def test_probe_limits_destination_and_avoids_global_network_writes(self) -> None:
        text = (ROOT / "ci/vpn/vpn-home-probe.py").read_text()
        assert "65536" in text
        assert "socks5h://127.0.0.1:" in text
        for forbidden in [
            "ip route add",
            "networksetup",
            "resolvectl dns",
            "sysctl -w",
        ]:
            assert forbidden not in text


class LegacyRetirementTests(unittest.TestCase):
    """Tests for LegacyRetirementTests."""

    def module(self) -> types.ModuleType:
        """Load the deployed legacy retirement tool."""
        return load_vpn_module("retire", ROOT / "ci/vpn/vpn-legacy-retire.py")

    def test_watchdog_removes_only_legacy_dependencies(self) -> None:
        m = self.module()
        old = {
            "state_dir": "/var/lib/homelab-vpn-failover",
            "tcp_endpoints": [["127.0.0.1", 32063], ["127.0.0.1", 32053]],
            "listen_ports": [
                {"protocol": "tcp", "port": 32063},
                {"protocol": "tcp", "port": 443},
            ],
            "native_unit_ports": {
                "homelab-vpn-primary.service": [
                    {"protocol": "tcp", "port": 32063},
                    {"protocol": "udp", "port": 32085},
                ]
            },
            "failure_threshold": 4,
            "confirmation_checks": 2,
        }
        after = m.watchdog_after(old)
        assert after["tcp_endpoints"] == [["127.0.0.1", 32053]]
        assert after["listen_ports"] == [{"protocol": "tcp", "port": 443}]
        assert after["failure_threshold"] == EXPECTED_FAILURE_THRESHOLD
        assert after["native_unit_ports"]["homelab-vpn-primary.service"] == [
            {"protocol": "udp", "port": 32085}
        ]
        assert len(entries(old["tcp_endpoints"])) == LEGACY_ENDPOINT_COUNT
        with pytest.raises(ValueError, match="Watchdog preimage drift"):
            m.watchdog_after(after)

    def test_collector_rewrite_is_narrow_and_not_repeatable(self) -> None:
        m = self.module()
        before = "ExecStart=python3 collector --ports 32087,32053,32083,32063 --state PRIVATEPATH"
        after = m.monitoring_after(before)
        assert after == "ExecStart=python3 collector --ports 32087,32053,32083 --state PRIVATEPATH"
        with pytest.raises(ValueError, match="preimage drift"):
            m.monitoring_after(after)

    def test_native_projection_only_disables_excluded_legacy(self) -> None:
        m = self.module()
        old = {
            "inbounds": [
                {
                    "id": 7,
                    "port": 32063,
                    "protocol": "vless",
                    "enable": 1,
                    "exclude_from_sub": 1,
                    "stream_settings": '{"network":"xhttp","security":"none"}',
                    "settings": '{"clients":[{"id":"PRESERVE"}]}',
                }
            ],
            "clients": [{"id": 1, "secret": "PRESERVE"}],
            "client_inbounds": [{"client_id": 1, "inbound_id": 7}],
            "hosts": [{"id": 7}],
        }
        after = m.desired(old)
        assert not after["inbounds"][0]["enable"]
        old_inbound = view(entries(old["inbounds"])[0])
        assert old_inbound["enable"]
        after["inbounds"][0]["enable"] = 1
        assert after == old
        old_inbound["exclude_from_sub"] = 0
        with pytest.raises(ValueError, match="excluded legacy plaintext inbound"):
            m.desired(old)

    def test_expected_sqlite_enable_flag_keeps_integer_sort_semantics(self) -> None:
        m = self.module()
        old = {
            "inbounds": [
                {
                    "id": 7,
                    "port": 32063,
                    "protocol": "vless",
                    "enable": 1,
                    "exclude_from_sub": 1,
                    "stream_settings": '{"network":"xhttp","security":"none"}',
                }
            ]
        }
        result = m.desired(old)
        assert type(result["inbounds"][0]["enable"]) is int
        assert result["inbounds"][0]["enable"] == 0
