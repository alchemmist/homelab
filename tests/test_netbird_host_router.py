"""Plans for NetBird on the existing socrat-0 and socrat-2 hosts."""

import importlib.util
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

BLOCKED_EXIT_CODE = 2
SPEC = importlib.util.spec_from_file_location(
    "netbird_host_router", ROOT / "scripts/netbird-host-router.py"
)
hr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hr)


def ready():
    facts = hr.default_facts()
    facts["management_url"] = "https://netbird.example.test"
    for host in facts["hosts"]:
        host["sudo_nopass"] = True
        host["runtime"] = "docker"
    return facts


def load_frontend(source):
    namespace = {}
    exec(source, namespace)
    return namespace


class HostRouterTests(unittest.TestCase):
    def test_default_check_is_render_only_and_blocked(self):
        result = subprocess.run(
            [os.sys.executable, str(ROOT / "scripts/netbird-host-router.py"), "check"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == BLOCKED_EXIT_CODE
        payload = json.loads(result.stdout)
        assert not payload["apply_allowed"]
        assert "management_url_unpublished" in payload["blockers"]
        assert any("noninteractive sudo" in item for item in payload["blockers"])
        assert any("runtime not proven" in item for item in payload["blockers"])

    def test_plan_refuses_the_git_worktree(self):
        target = ROOT / "deploy/netbird/host-router-out"
        result = subprocess.run(
            [
                os.sys.executable,
                str(ROOT / "scripts/netbird-host-router.py"),
                "plan",
                "--out",
                str(target),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == BLOCKED_EXIT_CODE
        assert "outside the Git worktree" in result.stderr
        assert not target.exists()

    def test_default_plan_records_memory_and_ssh_split(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "plan"
            result = subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / "scripts/netbird-host-router.py"),
                    "plan",
                    "--out",
                    str(target),
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == BLOCKED_EXIT_CODE
            plan = json.loads((target / "plan.json").read_text())
        assert not plan["apply_allowed"]
        assert "socrat-2 MemAvailable is 446 MiB (455948 KiB)" in plan["notes"]
        assert plan["ssh"] == {
            "address": "10.250.0.2",
            "port": 2222,
            "routers": ["socrat-0"],
            "destination": "socrat-2",
            "destination_delivery": "input",
            "ha": False,
        }
        assert plan["grafana"]["upstream"] == "10.250.0.3:443"
        assert not plan["grafana"]["shared_vip_published"]
        assert plan["grafana"]["policies"] == ["overlay-peer:socrat-0", "overlay-peer:socrat-2"]
        image = json.loads((ROOT / "deploy/netbird/images.lock.json").read_text())["images"][
            "client"
        ]
        assert plan["image"] == image["repository"] + ":" + image["tag"] + "@" + image["digest"]

    def test_firewall_uses_forward_on_socrat0_and_input_on_socrat2(self):
        _plan, rendered = hr.build(hr.default_facts())
        home = rendered["socrat-0"]["table.nft.sh"]
        vps = rendered["socrat-2"]["table.nft.sh"]
        assert home != vps
        home_forward = [
            line for line in hr.firewall_rules(home, "forward") if line.endswith("accept")
        ]
        vps_forward = [
            line for line in hr.firewall_rules(vps, "forward") if line.endswith("accept")
        ]
        expected_forward_rules = 2
        assert len(home_forward) == expected_forward_rules
        assert any(
            "daddr 10.250.0.2 tcp dport 2222" in line and 'oifname "wg-socrat"' in line
            for line in home_forward
        )
        assert vps_forward == []
        assert hr.firewall_rules(vps, "postrouting") == []
        assert "snat to 10.250.0.1" in "\n".join(hr.firewall_rules(home, "postrouting"))
        assert "10.250.0.2" not in vps
        assert "10.250.0.3" not in home
        assert "10.250.0.3" not in vps
        assert not any("dport 2222" in line for line in hr.firewall_rules(home, "input"))
        assert not any(
            "dport 2222" in line or "dport 22 " in line for line in hr.firewall_rules(vps, "input")
        )
        assert 'iifname != "nb-host" tcp dport 8443 drop' in home
        assert "add table ip netbird_host_router" in home
        assert "/etc/wireguard" not in home
        assert home.index('"$nft" -c -f') < home.index('"$nft" -f "$tmp"')

    def test_ssh_port_must_be_one_observed_choice(self):
        for port in (22, 2222):
            facts = ready()
            facts["ssh_port"] = port
            facts["ssh_probe"] = None
            plan, rendered = hr.build(facts)
            assert plan["ssh"]["port"] == port
            assert "dport %d" % port in rendered["socrat-0"]["table.nft.sh"]
            assert "10.250.0.2" not in rendered["socrat-2"]["table.nft.sh"]
        contradicted = hr.default_facts()
        contradicted["ssh_port"] = 22
        with self.assertRaises(ValueError):
            hr.validate(contradicted)
        for bad in (2224, 443, 22_222, None):
            facts = ready()
            facts["ssh_port"] = bad
            facts["ssh_probe"] = None
            with self.assertRaises(ValueError):
                hr.validate(facts)

    def test_destination_host_cannot_be_a_second_router(self):
        facts = hr.default_facts()
        facts["hosts"][1]["owned"] = ["109.120.141.60"]
        with self.assertRaisesRegex(ValueError, "own 10.250.0.2"):
            hr.validate(facts)
        assert hr.roles(hr.default_facts())["socrat-2"]["ssh_delivery"] == "input"
        assert not hr.roles(hr.default_facts())["socrat-2"]["ssh_routing_peer"]
        assert hr.roles(hr.default_facts())["socrat-0"]["ssh_routing_peer"]

    def test_grafana_frontend_denies_other_names_and_binds(self):
        _plan, rendered = hr.build(hr.default_facts())
        frontend = load_frontend(rendered["socrat-0"]["grafana-frontend.py"])
        assert frontend["UPSTREAM_IP"] == "10.250.0.3"
        upstream_port = 443
        assert frontend["UPSTREAM_PORT"] == upstream_port
        assert frontend["admit"]("grafana.socrat.alchemmist.xyz", "grafana.socrat.alchemmist.xyz")
        assert frontend["admit"](
            "Grafana.socrat.alchemmist.xyz", "grafana.socrat.alchemmist.xyz:8443"
        )
        for sni, host in (
            ("rancher.socrat.alchemmist.xyz", "grafana.socrat.alchemmist.xyz"),
            ("grafana.socrat.alchemmist.xyz", "rancher.socrat.alchemmist.xyz"),
            ("grafana.socrat.alchemmist.xyz", "10.250.0.3"),
            ("grafana.socrat.alchemmist.xyz.evil.test", "grafana.socrat.alchemmist.xyz"),
            ("", "grafana.socrat.alchemmist.xyz"),
            ("grafana.socrat.alchemmist.xyz", ""),
        ):
            assert not frontend["admit"](sni, host), (sni, host)
        context = frontend["upstream_context"]()
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        assert (
            frontend["sni_callback"](None, "rancher.socrat.alchemmist.xyz", None)
            == ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME
        )
        assert (
            frontend["sni_callback"](type("S", (), {})(), "grafana.socrat.alchemmist.xyz", None)
            is None
        )
        assert frontend["bind_allowed"]("100.96.0.8")
        for address in (
            "0.0.0.0",
            "109.120.141.60",
            "10.250.0.1",
            "10.250.0.2",
            "10.250.0.3",
            "192.168.0.23",
        ):
            assert not frontend["bind_allowed"](address), address

    def test_client_unit_is_pinned_and_constrained(self):
        _plan, rendered = hr.build(hr.default_facts())
        home = rendered["socrat-0"]["netbird-host-router.service"]
        vps = rendered["socrat-2"]["netbird-host-router.service"]
        for unit in (home, vps):
            assert (
                "netbirdio/netbird:0.82.0@sha256:eca5b274c635bfbb04ec6724a0712d1146190dd450eea199eeb83916fdd94965"
                in unit
            )
            assert "--cap-drop=ALL" in unit
            assert "--cap-add=NET_ADMIN" in unit
            assert "--memory=96m" in unit
            assert "--memory-swap=96m" in unit
            assert "--privileged" not in unit
            assert "docker.sock" not in unit
            assert "/etc/wireguard" not in unit
            assert "/etc/ssh" not in unit
        assert "NB_DISABLE_SERVER_ROUTES=false" in home
        assert "-e NB_DISABLE_SERVER_ROUTES=true" in vps
        up = rendered["socrat-2"]["netbird-up.sh"]
        assert "--allow-server-ssh=false" in up
        assert "--enable-ssh-root=false" in up
        assert "--interface-name" in up
        assert "nb-host" in up
        assert "authorized_keys" not in up
        assert "stat -c %a" in up
        assert "netbird_host_router_apply: false" in rendered["socrat-2"]["install.yml"]
        assert "99-netbird-host-router.conf" not in rendered["socrat-2"]["install.yml"]
        assert "net.ipv4.ip_forward=1\n" in rendered["socrat-0"]["99-netbird-host-router.conf"]

    def test_memory_cap_above_vps_headroom_blocks_apply(self):
        facts = hr.default_facts()
        facts["client_memory"] = "256m"
        plan, _rendered = hr.build(facts)
        assert not plan["apply_allowed"]
        assert any("memory caps" in item for item in plan["blockers"])
        assert "446 MiB" in plan["notes"][0]

    def test_shared_vip_and_existing_interfaces_fail_closed(self):
        facts = hr.default_facts()
        facts["upstream_address"] = "10.250.0.1"
        with self.assertRaisesRegex(ValueError, "upstream"):
            hr.validate(facts)
        facts = hr.default_facts()
        facts["frontend_port"] = 443
        with self.assertRaisesRegex(ValueError, "8443"):
            hr.validate(facts)
        facts = hr.default_facts()
        facts["interface"] = "wg-socrat"
        with self.assertRaises(ValueError):
            hr.validate(facts)
        facts = hr.default_facts()
        facts["overlay_cidr"] = "10.250.0.0/24"
        with self.assertRaises(ValueError):
            hr.validate(facts)

    def test_apply_copies_only_owned_files_after_blockers_clear(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            facts_path = base / "facts.json"
            facts_path.write_text(json.dumps(ready()))
            out = base / "plan"
            planned = subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / "scripts/netbird-host-router.py"),
                    "plan",
                    "--facts",
                    str(facts_path),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
            assert planned.returncode == 0, planned.stderr
            blocked = subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / "scripts/netbird-host-router.py"),
                    "apply",
                    "--plan",
                    str(out),
                    "--root",
                    str(base / "nope"),
                    "--host",
                    "socrat-2",
                ],
                capture_output=True,
                text=True,
            )
            # ready() facts have no blockers, so replace the plan with the default blocked one
            assert blocked.returncode == 0, blocked.stderr
            default_out = base / "blocked"
            blocked_plan = subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / "scripts/netbird-host-router.py"),
                    "plan",
                    "--out",
                    str(default_out),
                ],
                capture_output=True,
                text=True,
            )
            assert blocked_plan.returncode == BLOCKED_EXIT_CODE
            refused = subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / "scripts/netbird-host-router.py"),
                    "apply",
                    "--plan",
                    str(default_out),
                    "--root",
                    str(base / "refused"),
                    "--host",
                    "socrat-2",
                ],
                capture_output=True,
                text=True,
            )
            assert refused.returncode == BLOCKED_EXIT_CODE
            assert "blockers remain" in refused.stderr
            assert not (base / "refused").exists()
            root = base / "root"
            applied = subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / "scripts/netbird-host-router.py"),
                    "apply",
                    "--plan",
                    str(out),
                    "--root",
                    str(root),
                    "--host",
                    "socrat-0",
                    "--overlay-ip",
                    "100.96.8.8",
                ],
                capture_output=True,
                text=True,
            )
            assert applied.returncode == 0, applied.stderr
            installed = (root / "usr/local/libexec/netbird-host-router/table.nft.sh").read_text()
            assert "100.96.8.8" in installed
            assert hr.OVERLAY_TOKEN not in installed
            assert (root / "etc/systemd/system/netbird-host-router.service").is_file()
            assert (root / "etc/sysctl.d/99-netbird-host-router.conf").is_file()
            assert not (root / "etc/wireguard").exists()
            assert not list(root.rglob("*wg-socrat*"))
            public = subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / "scripts/netbird-host-router.py"),
                    "apply",
                    "--plan",
                    str(out),
                    "--root",
                    str(base / "public"),
                    "--host",
                    "socrat-0",
                    "--overlay-ip",
                    "109.120.141.60",
                ],
                capture_output=True,
                text=True,
            )
            assert public.returncode == BLOCKED_EXIT_CODE
            assert not (base / "public").exists()
            tampered = out / "socrat-0" / "netbird-up.sh"
            tampered.write_text(tampered.read_text() + "\n# tamper\n")
            again = subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / "scripts/netbird-host-router.py"),
                    "apply",
                    "--plan",
                    str(out),
                    "--root",
                    str(base / "tamper"),
                    "--host",
                    "socrat-0",
                ],
                capture_output=True,
                text=True,
            )
            assert again.returncode == BLOCKED_EXIT_CODE
            assert "digest mismatch" in again.stderr

    def test_apply_refuses_a_symlink_outside_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            out = base / "plan"
            facts = base / "facts.json"
            facts.write_text(json.dumps(ready()))
            planned = subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / "scripts/netbird-host-router.py"),
                    "plan",
                    "--facts",
                    str(facts),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
            assert planned.returncode == 0, planned.stderr
            outside = base / "outside"
            outside.mkdir()
            root = base / "root"
            root.mkdir()
            (root / "etc").symlink_to(outside)
            result = subprocess.run(
                [
                    os.sys.executable,
                    str(ROOT / "scripts/netbird-host-router.py"),
                    "apply",
                    "--plan",
                    str(out),
                    "--root",
                    str(root),
                    "--host",
                    "socrat-2",
                    "--overlay-ip",
                    "100.96.9.9",
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode == BLOCKED_EXIT_CODE
            assert not list(outside.rglob("*"))


if __name__ == "__main__":
    unittest.main()
