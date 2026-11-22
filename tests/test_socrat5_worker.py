"""Headless native VM worker invariants; no live operations or credentials."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class Socrat5WorkerSourceTests(unittest.TestCase):
    """Check native socrat-5 worker source without applying it."""

    def test_native_vm_has_full_nfs_admission(self) -> None:
        """Keep full NFS admission on the headless native worker."""
        host = yaml.safe_load((ROOT / "ansible/inventory/host_vars/socrat-5.yml").read_text())
        assert host["k3s_worker_taints"] == []
        assert host["k3s_worker_nfs_enabled"]
        assert host["k3s_worker_extra_node_labels"] == ["homelab.io/nfs=true"]
        assert host["homelab_headless"]
        assert host["k3s_worker_manage_kernel_modules"]
        assert not host["k3s_worker_user_namespace"]
        assert not host["k3s_worker_prefer_bundled_bin"]

    def test_native_nfs_does_not_recreate_the_lxc_storage_guard(self) -> None:
        """Keep the native NFS guard distinct from the retired LXC binding."""
        play = yaml.safe_load((ROOT / "ansible/playbooks/socrat-5-worker.yml").read_text())[0]
        legacy = next(
            t
            for t in play["pre_tasks"]
            if t["name"]
            == "Require the owned storage admission boundary before worker provisioning"
        )
        native = next(
            t
            for t in play["pre_tasks"]
            if t["name"] == "Require obsolete no-NFS binding to be retired for native NFS workers"
        )
        assert "not (k3s_worker_nfs_enabled" in legacy["when"]
        assert "k3s_worker_nfs_enabled" in native["when"]
        assert "validatingadmissionpolicybinding" in native["ansible.builtin.command"]["cmd"]
        guard = yaml.safe_load((ROOT / "ansible/playbooks/socrat-5-storage-guard.yml").read_text())[
            0
        ]
        assert "k3s_worker_nfs_enabled" in guard["pre_tasks"][0]["ansible.builtin.assert"]["that"]

    def test_original_n8n_pv_requires_dedicated_data_mounts(self) -> None:
        """Keep the original n8n data bind and its required parent mounts."""
        host = yaml.safe_load((ROOT / "ansible/inventory/host_vars/socrat-5.yml").read_text())
        assert host["k3s_worker_data_bind_mounts"] == [
            {
                "source": "/mnt/files/homelab/n8n-socrat5/data",
                "target": "/var/lib/rancher/k3s/storage/n8n-socrat5",
            }
        ]
        assert host["k3s_worker_required_mounts"] == [
            "/mnt/files",
            "/var/lib/rancher/k3s/storage/n8n-socrat5",
        ]
        play = yaml.safe_load((ROOT / "ansible/playbooks/socrat-5-worker.yml").read_text())[0]
        tasks = play["pre_tasks"]
        mount = next(t for t in tasks if "ansible.posix.mount" in t)["ansible.posix.mount"]
        assert mount["opts"] == "bind,x-systemd.requires-mounts-for=/mnt/files"
        assert mount["state"] == "mounted"
        dropin = next(
            t
            for t in tasks
            if t.get("ansible.builtin.copy", {})
            .get("dest", "")
            .endswith("50-worker-data-mounts.conf")
        )
        assert "RequiresMountsFor=" in dropin["ansible.builtin.copy"]["content"]
        assert (
            "ExecStartPre=/usr/bin/mountpoint --quiet" in dropin["ansible.builtin.copy"]["content"]
        )
        assert "database.sqlite" in tasks[0]["ansible.builtin.stat"]["path"]

    def test_exact_advertised_home_routes_only(self) -> None:
        """Keep only the existing advertised home peer routes."""
        host = yaml.safe_load((ROOT / "ansible/inventory/host_vars/socrat-5.yml").read_text())
        assert host["wg_socrat_extra_allowed_peer_ips"] == {
            "socrat-5": {
                "socrat-0": ["192.168.0.23/32"],
                "socrat-1": ["192.168.0.24/32"],
            }
        }

    def test_only_worker5_nl_endpoint_changes_to_existing_relay(self) -> None:
        """Keep worker5's NL endpoint pinned to the existing relay."""
        group = yaml.safe_load((ROOT / "ansible/inventory/group_vars/Socrat.yml").read_text())
        peers = group["wg_socrat_peer_endpoints"]
        assert peers["socrat-5"]["socrat-2"] == peers["socrat-0"]["socrat-2"]
        assert peers["socrat-5"]["socrat-2"] == "91.189.82.238:51832"
        assert peers["socrat-5"]["socrat-3"] == "46.8.146.172:46559"

    def test_unprivileged_exporter_can_traverse_fresh_parent_directories(self) -> None:
        """Keep parent directories traversable for the unprivileged exporter."""
        play = yaml.safe_load((ROOT / "ansible/playbooks/otel-production-agents.yml").read_text())[
            0
        ]
        task = next(
            t
            for t in play["tasks"]
            if t.get("name") == "Create native textfile source and read-only namespace mountpoint"
        )
        assert task["ansible.builtin.file"]["mode"] == "0755"
        for path in [
            "/host",
            "/host/root",
            "/host/root/var",
            "/host/root/var/lib",
            "/host/root/var/lib/node_exporter",
            "/var/lib/node_exporter",
        ]:
            assert path in task["loop"]

    def test_password_tasks_are_private_and_do_not_change_ssh_policy(self) -> None:
        """Keep password tasks private and leave SSH policy untouched."""
        play = yaml.safe_load((ROOT / "ansible/playbooks/socrat-5-headless.yml").read_text())[0]
        users = [t for t in play["pre_tasks"] if "ansible.builtin.user" in t]
        assert {t["ansible.builtin.user"]["name"] for t in users} == {
            "alchemmist",
            "root",
        }
        assert all(t["no_log"] for t in users)
        assert all("password" in t["ansible.builtin.user"] for t in users)
        assert "sshd_config" not in str(users)

    def test_no_desktop_roles(self) -> None:
        """Keep the headless play limited to the starship role."""
        play = yaml.safe_load((ROOT / "ansible/playbooks/socrat-5-headless.yml").read_text())[0]
        assert play["roles"] == ["starship"]

    def test_native_pipeline_is_durable(self) -> None:
        """Keep native file storage durable and retries unbounded."""
        cfg = yaml.safe_load((ROOT / "deploy/monitoring/native/socrat-5/agent.yaml").read_text())
        assert cfg["extensions"]["file_storage"]["fsync"]
        for name in ["journald", "filelog"]:
            assert cfg["receivers"][name]["retry_on_failure"]["max_elapsed_time"] == "0s"

    def test_real_blockers_documented(self) -> None:
        """Keep the recorded native-worker blockers visible."""
        text = (ROOT / "docs/records/handoffs/socrat-5-worker-20261110.md").read_text()
        assert "Negative NetworkPolicy acceptance failed" in text
        assert "NFS mount denied" in text
        assert "Owner-approved no-NFS profile" in text
