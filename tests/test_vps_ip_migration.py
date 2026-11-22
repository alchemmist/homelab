"""Offline migration contracts. Never connect to or mutate managed hosts."""

import importlib.util
import json
import socket
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]

SOURCE_DB_MODE = 0o640
PREIMAGE_FILE_MODE = 0o600
BACKUP_DIR_MODE = 0o700
SPEC = importlib.util.spec_from_file_location("vps_migration", ROOT / "ansible/scripts/vps-ip-migration.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
OLD, NEW = "1.1.1.1", "8.8.8.8"


class AddressTests(unittest.TestCase):
    """Tests for AddressTests."""

    def test_distinct_canonical_public_ipv4(self) -> None:
        M.addresses(OLD, NEW)
        for old, new in [
            (OLD, OLD),
            ("10.0.0.1", NEW),
            ("01.1.1.1", NEW),
            ("::1", NEW),
            ("bad", NEW),
            ("224.0.0.1", NEW),
        ]:
            with self.subTest(old=old, new=new), self.assertRaises(M.MigrationError):
                M.addresses(old, new)

    def test_home_entrance_cannot_be_mistaken_for_old_vps(self) -> None:
        with self.assertRaises(M.MigrationError):
            M.validate_dns_anchor('HOME = "1.1.1.1"\nVPS = "8.8.8.8"\n', OLD, NEW)

    def test_replace_exact_ip_not_prefix(self) -> None:
        value = OLD + ":443 " + OLD + "/32 11.1.1.1 1.1.1.10"
        assert M.replace_address(value, OLD, NEW) == NEW + ":443 " + NEW + "/32 11.1.1.1 1.1.1.10"


class RepositoryTests(unittest.TestCase):
    """Tests for RepositoryTests."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        for name in M.SOURCE_FILES:
            p = self.repo / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("endpoint " + OLD + ":443\n")
        (self.repo / "ansible/scripts/public_dns_zone.py").write_text(
            'HOME = "9.9.9.9"\nVPS = "' + OLD + '"\n'
        )
        self.backup = self.base / "private-backups"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "-c",
                "commit.gpgsign=false",
                "-c",
                "user.name=Offline Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--no-verify",
                "-qm",
                "fixture",
            ],
            check=True,
        )

    def test_audit_is_read_only(self) -> None:
        before = {p: p.read_bytes() for p in self.repo.rglob("*") if p.is_file()}
        report = M.repository(self.repo, OLD, NEW, backup_root=self.backup)
        assert not report["changed"]
        assert len(report["planned_files"]) == len(M.SOURCE_FILES)
        assert not self.backup.exists()
        assert before == {p: p.read_bytes() for p in self.repo.rglob("*") if p.is_file()}

    def test_apply_private_preimages_idempotence_and_history_not_touched(self) -> None:
        historical = self.repo / "docs/old-incident.md"
        historical.parent.mkdir()
        historical.write_text(OLD)
        outside = self.repo / "unreviewed.conf"
        outside.write_text(OLD)
        source = self.repo / M.SOURCE_FILES[0]
        source.chmod(0o640)
        report = M.repository(self.repo, OLD, NEW, True, self.backup)
        assert report["changed"]
        assert historical.read_text() == OLD
        assert outside.read_text() == OLD
        assert stat.S_IMODE(source.stat().st_mode) == SOURCE_DB_MODE
        preimage = Path(report["preimages"]) / M.SOURCE_FILES[0]
        assert OLD in preimage.read_text()
        assert stat.S_IMODE(preimage.stat().st_mode) == PREIMAGE_FILE_MODE
        assert stat.S_IMODE(self.backup.stat().st_mode) == BACKUP_DIR_MODE
        again = M.repository(self.repo, OLD, NEW, True, self.backup)
        assert not again["changed"]
        assert len(list(self.backup.iterdir())) == 1

    def test_backup_must_be_outside_worktree(self) -> None:
        with self.assertRaises(M.MigrationError):
            M.repository(self.repo, OLD, NEW, True, self.repo / "private")

    def test_third_address_anchor_fails_closed(self) -> None:
        (self.repo / "ansible/scripts/public_dns_zone.py").write_text('VPS = "9.9.9.9"\n')
        with self.assertRaises(M.MigrationError):
            M.repository(self.repo, OLD, NEW)

    def test_missing_or_symlink_source_fails_closed(self) -> None:
        p = self.repo / M.SOURCE_FILES[0]
        p.unlink()
        with self.assertRaises(M.MigrationError):
            M.repository(self.repo, OLD, NEW)
        p.symlink_to(self.repo / M.SOURCE_FILES[1])
        with self.assertRaises(M.MigrationError):
            M.repository(self.repo, OLD, NEW)

    def test_partial_receipt_blocks_blind_rerun(self) -> None:
        store = M.Preimages(self.backup, OLD + "-to-" + NEW)
        store.receipt({"state": "partial-failure-stop-and-investigate"})
        with self.assertRaises(M.MigrationError):
            M.repository(self.repo, OLD, NEW, backup_root=self.backup)

    def test_dirty_owned_source_is_preserved(self) -> None:
        path = self.repo / M.SOURCE_FILES[0]
        path.write_text(path.read_text() + "concurrent change")
        with self.assertRaises(M.MigrationError):
            M.repository(self.repo, OLD, NEW, True, self.backup)
        assert "concurrent change" in path.read_text()
        assert not self.backup.exists()

    def test_parent_symlink_escape_is_rejected(self) -> None:
        outside = self.base / "external"
        outside.mkdir()
        parent = self.repo / "deploy/socrat-bot"
        shutil = __import__("shutil")
        shutil.rmtree(parent)
        (outside / "values.yaml").write_text(OLD)
        parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(M.MigrationError):
            M.repository(self.repo, OLD, NEW)
        assert (outside / "values.yaml").read_text() == OLD

    def test_source_failure_leaves_stop_receipt(self) -> None:
        with patch.object(M, "write_changes", side_effect=M.MigrationError("injected failure")):
            with self.assertRaises(M.MigrationError):
                M.repository(self.repo, OLD, NEW, True, self.backup)
        receipts = list(self.backup.glob("*/receipt.json"))
        assert len(receipts) == 1
        assert (
            json.loads(receipts[0].read_text())["state"] == "partial-failure-stop-and-investigate"
        )

    def test_file_drift_is_not_overwritten(self) -> None:
        changes = M.file_plan([self.repo / M.SOURCE_FILES[0]], OLD, NEW)
        changes[0][0].write_text("concurrent edit")
        store = M.Preimages(self.backup, "test")
        with self.assertRaises(M.MigrationError):
            M.write_changes(changes, store, lambda p: p.name)
        assert changes[0][0].read_text() == "concurrent edit"


class DatabaseTests(unittest.TestCase):
    """Tests for DatabaseTests."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.db = self.base / "x-ui.db"
        with sqlite3.connect(self.db) as c:
            c.execute("CREATE TABLE hosts(id INTEGER PRIMARY KEY, address TEXT, credential TEXT)")
            c.executemany(
                "INSERT INTO hosts VALUES(?,?,?)",
                [(1, OLD, "private-sentinel"), (2, "vpn.example.com", "keep")],
            )
            c.execute("CREATE TABLE clients(id INTEGER PRIMARY KEY, secret BLOB, up INTEGER)")
            c.execute("INSERT INTO clients VALUES(1,?,123)", (b"credential",))

    def test_production_sql_write_prohibited_and_backup_read_only(self) -> None:
        before = self.db.read_bytes()
        store = M.Preimages(self.base / "backups", "test")
        with self.assertRaisesRegex(M.MigrationError, "native API"):
            M.migrate_database(self.db, OLD, NEW, store)
        backup = M.backup_database(self.db, store)
        assert self.db.read_bytes() == before
        with sqlite3.connect(backup) as c:
            assert c.execute("SELECT address FROM hosts WHERE id=1").fetchone()[0] == OLD
            assert c.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert stat.S_IMODE(backup.stat().st_mode) == PREIMAGE_FILE_MODE

    def test_nonliteral_address_needs_review(self) -> None:
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE hosts SET address=? WHERE id=1", (OLD + ":443",))
        with self.assertRaises(M.MigrationError):
            M.db_plan(self.db, OLD)

    def test_wrong_schema_and_corrupt_database_fail_before_mutation(self) -> None:
        with sqlite3.connect(self.db) as c:
            c.execute("DROP TABLE hosts")
        with self.assertRaises(M.MigrationError):
            M.db_plan(self.db, OLD)
        self.db.write_bytes(b"not sqlite")
        with self.assertRaises(sqlite3.DatabaseError):
            M.db_plan(self.db, OLD)


class RuntimeTests(unittest.TestCase):
    """Tests for RuntimeTests."""

    def test_only_old_peer_endpoint_is_selected(self) -> None:
        a, b = "A" * 43 + "=", "B" * 43 + "="
        text = f"[Peer]\nPublicKey = {a}\nEndpoint = {OLD}:51830\nAllowedIPs = 10.250.0.2/32\n[Peer]\nPublicKey = {b}\nEndpoint = 127.0.0.1:51840\n"
        assert M.wg_endpoint_changes(text, OLD, NEW) == [(a, NEW + ":51830")]
        with self.assertRaises(M.MigrationError):
            M.wg_endpoint_changes("[Peer]\nEndpoint = " + OLD + ":123", OLD, NEW)

    def test_do_not_retarget_home_peer(self) -> None:
        text = (
            "[Peer]\nPublicKey = "
            + "A" * 43
            + "=\nEndpoint = "
            + OLD
            + ":51830\nAllowedIPs = 10.250.0.1/32\n"
        )
        with self.assertRaises(M.MigrationError):
            M.wg_endpoint_changes(text, OLD, NEW)

    def test_only_owned_native_services(self) -> None:
        changes = [
            (Path("/etc/hosts"), "", ""),
            (Path("/etc/wireguard/wg-socrat.conf"), "", ""),
            (Path("/etc/knot/knot.conf"), "", ""),
        ]
        assert M.required_services(changes) == ["knot.service"]
        assert "k3s.service" not in M.required_services(changes)

    def test_reviewed_restarting_transport_and_dormant_guard(self) -> None:
        services = ["wireguard-tcp-transport.service", "wireguard-tcp-transport-guard.service"]
        states = dict(zip(services, ["activating", "inactive"], strict=True))
        with patch.object(
            M, "run", side_effect=lambda a: "auto-restart" if "SubState" in a else states[a[2]]
        ):
            with self.assertRaises(M.MigrationError):
                M.service_plan(services)
            assert M.service_plan(services, states) == ([services[0]], [services[1]])
            with self.assertRaises(M.MigrationError):
                M.service_plan(services, {services[0]: "inactive"})

    def test_reviewed_dormant_service_becoming_active_stops(self) -> None:
        with patch.object(M, "run", return_value="active"):
            with self.assertRaisesRegex(M.MigrationError, "drifted"):
                M.service_plan(["knot.service"], {"knot.service": "inactive"})

    def test_wrong_host_and_unassigned_address_fail_before_files(self) -> None:
        with patch.object(socket, "gethostname", return_value="socrat-2"):
            with self.assertRaises(M.MigrationError):
                M.host("socrat-0", OLD, NEW)
            with patch.object(M, "run", return_value="[]"):
                with self.assertRaises(M.MigrationError):
                    M.host("socrat-2", OLD, NEW, require_assigned=True)

    def test_command_failure_never_echoes_secret_stderr(self) -> None:
        fake = type("Result", (), {"returncode": 1, "stderr": "private-sentinel", "stdout": ""})()
        with patch.object(M.subprocess, "run", return_value=fake):
            with self.assertRaises(M.MigrationError) as caught:
                M.run(["example", "private-argument"])
        assert "private" not in str(caught.exception)

    def test_guard_adds_new_before_removing_exact_old_rule(self) -> None:
        calls: list[list[str]] = []
        with (
            patch.object(M, "run", side_effect=lambda a: calls.append(a) or ""),
            patch.object(M.subprocess, "run", return_value=type("R", (), {"returncode": 0})()),
        ):
            M.refresh_guard(
                "/usr/bin/python3 /usr/local/libexec/wireguard-tcp-transport-guard.py wlan0 "
                + OLD
                + " 51830",
                NEW,
            )
        assert NEW in calls[0]
        assert calls[1][:5] == ["iptables", "-w", "10", "-D", "INPUT"]
        assert OLD in calls[1]


class OrchestrationTests(unittest.TestCase):
    """Tests for OrchestrationTests."""

    def test_audit_default_and_explicit_restart_gate(self) -> None:
        defaults = yaml.safe_load(
            (ROOT / "ansible/roles/vps_ip_migration/defaults/main.yml").read_text()
        )
        assert defaults["vps_ip_migration_apply"] is False
        assert defaults["vps_ip_migration_allow_service_restarts"] is False
        plays = yaml.safe_load((ROOT / "ansible/playbooks/vps-ip-migration.yml").read_text())
        assert plays[1]["hosts"] == "Socrat"
        assert plays[1]["any_errors_fatal"]
        assert plays[3]["hosts"] == "socrat-2"
        assert plays[4]["serial"] == 1
        for play in plays[2:5]:
            for task in play["tasks"]:
                assert "not ansible_check_mode" in task["when"]
        content = json.dumps(plays)
        assert "rollout restart" not in content
        assert "wg-quick down" not in content

    def test_skill_has_manual_acceptance_and_real_external_test(self) -> None:
        skill = (ROOT / ".agents/skills/vps-ip-migration/SKILL.md").read_text()
        for term in [
            "vps-ip-migration.yml",
            "hosts.address",
            "glue",
            "otel-cluster-logs-activate.yml",
            "getWebhookInfo",
            "literal NEW",
            "imported",
        ]:
            assert term in skill
        assert (ROOT / ".agents/skills/vps-ip-migration/references/acceptance.md").is_file()
