"""Offline checks for detaching symlinked account configuration inside a temp home."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "ansible/roles/node_config_isolation/files/isolate_node_configs.py"
)
SPEC = importlib.util.spec_from_file_location("node_config_isolation", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IsolationTests(unittest.TestCase):
    """Materialize configuration links under a disposable home directory."""

    def setUp(self) -> None:
        """Create a disposable home with a dotfiles source."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.source = self.home / "code/dotfiles"
        self.source.mkdir(parents=True)
        (self.home / ".config").mkdir()

    def test_directory_and_nested_file_links_materialize_without_source_changes(
        self,
    ) -> None:
        """Copy linked config into the home and leave the dotfiles source untouched."""
        source = self.source / "hypr"
        source.mkdir()
        (source / "hyprland.conf").write_text("original")
        (source / "hyprland.conf").chmod(0o640)
        (self.home / ".config/hypr").symlink_to(source, target_is_directory=True)
        waybar = self.home / ".config/waybar"
        waybar.mkdir()
        (waybar / "config").symlink_to(source / "hyprland.conf")
        result = MODULE.isolate(self.home)
        assert result["changed"]
        assert not (self.home / ".config/hypr").is_symlink()
        assert not (waybar / "config").is_symlink()
        group_readable_mode = 0o640
        assert (
            self.home / ".config/hypr/hyprland.conf"
        ).stat().st_mode & 511 == group_readable_mode
        (self.home / ".config/hypr/hyprland.conf").write_text("managed")
        assert (source / "hyprland.conf").read_text() == "original"
        assert (Path(result["backup"]) / "original/.config/hypr").is_symlink()
        assert (Path(result["backup"]) / "original/.config/waybar/config").is_symlink()
        assert not MODULE.isolate(self.home)["changed"]

    def test_profile_script_and_service_links_are_detached(self) -> None:
        """Replace profile, script, and service links without editing their source."""
        source = self.source / "file"
        source.write_text("original")
        paths = [
            ".zshrc",
            ".tmux.conf",
            "scripts/caffeine-manager.sh",
            ".config/systemd/user/caffeine-lid-inhibit.service",
        ]
        for relative in paths:
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(source)
        MODULE.isolate(self.home)
        for relative in paths:
            assert not (self.home / relative).is_symlink()
        assert source.read_text() == "original"

    def test_scripts_directory_symlink_preserves_unmanaged_scripts(self) -> None:
        """Materialize a scripts directory link and keep unmanaged script text."""
        source = self.source / "scripts"
        source.mkdir()
        (source / "other.sh").write_text("keep")
        (self.home / "scripts").symlink_to(source, target_is_directory=True)
        MODULE.isolate(self.home)
        assert not (self.home / "scripts").is_symlink()
        assert (self.home / "scripts/other.sh").read_text() == "keep"
        assert (source / "other.sh").read_text() == "keep"

    def test_dry_run_is_read_only(self) -> None:
        """Report a pending change without writing a backup or replacing the link."""
        source = self.source / "profile"
        source.write_text("original")
        (self.home / ".zprofile").symlink_to(source)
        result = MODULE.isolate(self.home, check=True)
        assert result["changed"]
        assert result["backup"] is None
        assert (self.home / ".zprofile").is_symlink()
        assert not (self.home / ".local").exists()

    def test_outside_home_rejected_before_any_change(self) -> None:
        """Reject a link that leaves the home before creating isolation state."""
        (self.home / ".tmux.conf").symlink_to("/etc/passwd")
        with self.assertRaisesRegex(ValueError, "outside"):
            MODULE.isolate(self.home)
        assert (self.home / ".tmux.conf").is_symlink()
        assert not (self.home / ".local").exists()

    def test_nested_cycle_rejected(self) -> None:
        """Reject a configuration symlink cycle."""
        source = self.source / "hypr"
        source.mkdir()
        (source / "cycle").symlink_to(source, target_is_directory=True)
        (self.home / ".config/hypr").symlink_to(source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "cycle"):
            MODULE.isolate(self.home)

    def test_symlink_parent_rejected(self) -> None:
        """Reject isolation when a parent directory is itself a symlink."""
        (self.home / ".config").rmdir()
        (self.home / ".config").symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "parent"):
            MODULE.isolate(self.home)


if __name__ == "__main__":
    unittest.main()
