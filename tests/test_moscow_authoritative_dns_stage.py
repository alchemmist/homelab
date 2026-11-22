"""Offline safety contract for the undelegated, Moscow-only DNS stage."""

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAY = ROOT / "ansible/playbooks/moscow-authoritative-dns-stage.yml"


def test_stage_is_one_host_and_read_only_by_default() -> None:
    """Require one socrat-4 play that stays read-only until apply is enabled."""
    plays = yaml.safe_load(PLAY.read_text())
    assert len(plays) == 1
    play = plays[0]
    assert play["hosts"] == "socrat-4"
    assert play["become"] is False
    assert play["vars"]["moscow_dns_apply"] is False
    blocks = [t for t in play["tasks"] if "block" in t]
    assert len(blocks) == 1
    assert blocks[0]["when"] == "moscow_dns_apply | bool"
    assert blocks[0]["become"] is True
    assert (
        "moscow_dns_approved_renderer_sha256 == moscow_dns_renderer.stat.checksum"
        in blocks[0]["block"][0]["ansible.builtin.assert"]["that"]
    )


def test_listener_does_not_replace_relay_or_require_wireguard() -> None:
    """Keep the public listener beside the relay, with no WireGuard, k3s, or firewall hooks."""
    play = yaml.safe_load(PLAY.read_text())[0]
    assert play["vars"]["public_dns_listen"] == {"socrat-4": ["91.189.82.238@53"]}
    assert play["vars"]["public_dns_install_policy_rc_d"] == 101
    assert play["vars"]["public_dns_config_validate"] == "/usr/sbin/knotc -c %s conf-check"
    assert "public_dns_extra_listen" not in play["vars"]
    assert "public_dns_transit_listener_enabled" not in play["vars"]
    text = PLAY.read_text()
    verify = play["tasks"][-1]["block"][-1]
    assert verify["homelab_systemd_probe"] == {"units": ["knot", "homelab-vpn-dns-transit"]}
    assert verify["changed_when"] is False
    assert "k3s-agent.service" not in text
    assert "iptables" not in text
    assert "nft " not in text


def test_staging_does_not_publish_moscow_web_records() -> None:
    """Publish the VPN address from staging and withhold Moscow web failover names."""
    spec = importlib.util.spec_from_file_location(
        "moscow_stage_zone", ROOT / "ansible/scripts/public_dns_zone.py"
    )
    zone = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(zone)
    for home, vps in [(True, True), (True, False), (False, True), (False, False)]:
        text = zone.render(123, home, vps)
        for name in zone.FAILOVER:
            assert (f"{name} IN A 91.189.82.238" in text.splitlines()) == (name == "monori")
        assert "vpn IN A 91.189.82.238" in text


def test_shared_role_safety_knobs_are_opt_in() -> None:
    """Leave policy-rc.d, validation, and backup omitted unless the play sets them."""
    text = (ROOT / "ansible/roles/public_authoritative_dns/tasks/main.yml").read_text()
    assert 'policy_rc_d: "{{ public_dns_install_policy_rc_d | default(omit) }}"' in text
    assert 'validate: "{{ public_dns_config_validate | default(omit) }}"' in text
    assert 'backup: "{{ public_dns_config_backup | default(false) }}"' in text
