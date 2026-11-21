"""Static ShellCheck coverage and synthetic widget fixtures for the second shell batch."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUCCESS_EXIT = 0
TOOL_TIMEOUT_SECONDS = 15
CAFFEINE_IGNORES = 2
NIGHTNODE_IGNORES = 4
STATUS_DEFAULT_ARMS = 3
TOGGLE_FILE_TESTS = 2
CLEAN_SHELL = (
    "ansible/roles/desktop_environment/files/caffeine-manager.sh",
    "ansible/roles/desktop_panel/files/toggle_noscreenshare.sh",
    "ansible/roles/starship/files/arc-refresh.sh",
    "ansible/roles/starship/files/arc_dots.sh",
    "ansible/roles/starship/files/arc_metrics.sh",
    "ansible/roles/starship/files/arc_status.sh",
    "scripts/testing-class-wg-guard.sh",
)
WIDGETS = (
    "ansible/roles/starship/files/arc-refresh.sh",
    "ansible/roles/starship/files/arc_dots.sh",
    "ansible/roles/starship/files/arc_metrics.sh",
    "ansible/roles/starship/files/arc_status.sh",
)
NIGHTNODE = "scripts/nightnode/nightnode"
GUARD = "scripts/testing-class-wg-guard.sh"
CAFFEINE = "ansible/roles/desktop_environment/files/caffeine-manager.sh"
TOGGLE = "ansible/roles/desktop_panel/files/toggle_noscreenshare.sh"
REFRESH = "ansible/roles/starship/files/arc-refresh.sh"
DOTS = "ansible/roles/starship/files/arc_dots.sh"
METRICS = "ansible/roles/starship/files/arc_metrics.sh"
STATUS = "ansible/roles/starship/files/arc_status.sh"
AHEAD = "\uf176"
BEHIND = "\uf175"
STATUS_MARK = "\uf444"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"
STATUS_ENABLED = (
    '{"text":"Hypridle enabled","class":"enabled","alt":"enabled",'
    '"tooltip":"Обычный режим: таймеры hypridle и реакция на крышку включены"}'
)
STATUS_DISABLED = (
    '{"text":"Caffeine enabled","class":"disabled","alt":"disabled",'
    '"tooltip":"Режим молнии: таймеры hypridle отключены, закрытие крышки игнорируется"}'
)
STATUS_PARTIAL = (
    '{"text":"Hypridle disabled","class":"disabled","alt":"disabled",'
    '"tooltip":"Hypridle остановлен, но блокировка крышки не активна"}'
)
ARC = """#!/bin/sh
printf '%s\n' "$*" >> "${ARC_ARGS}"
cmd=$1
shift
case "${cmd}" in
  info)
    if [ "${ARC_INFO_RC:-0}" -ne 0 ]; then
      exit "${ARC_INFO_RC}"
    fi
    printf '%s\n' "${ARC_INFO_TEXT-}"
    ;;
  diff)
    printf '%s\n' "${ARC_DIFF_TEXT-}"
    exit "${ARC_DIFF_RC:-0}"
    ;;
  log)
    printf '%s\n' "${ARC_LOG_TEXT-}"
    exit "${ARC_LOG_RC:-0}"
    ;;
  status)
    printf '%s\n' "${ARC_STATUS_TEXT-}"
    exit "${ARC_STATUS_RC:-0}"
    ;;
  stash)
    printf '%s\n' "${ARC_STASH_TEXT-}"
    exit "${ARC_STASH_RC:-0}"
    ;;
  *)
    printf 'unexpected arc command\n' >&2
    exit 99
    ;;
esac
"""
PYTHON = """#!/bin/sh
printf '%s\n' "$*" >> "${PYTHON_LOG}"
exit 0
"""


def _executable(name: str) -> str:
    """Return an absolute tool path from PATH."""
    found = shutil.which(name)
    if found is None:
        message = "required executable is not on PATH"
        raise RuntimeError(message)
    return found


def _run(
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    """Run one static checker or synthetic widget fixture."""
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT_SECONDS,
        check=False,
    )


def _shell_env() -> dict[str, str]:
    """Environment for syntax checks. It does not include caller secrets."""
    return {"PATH": "/usr/bin" + os.pathsep + "/bin", "LANG": "C", "LC_ALL": "C"}


def _items(stdout: str) -> list[dict[str, object]]:
    """Parse ShellCheck JSON without accepting a non-list payload."""
    parsed = json.loads(stdout)
    assert isinstance(parsed, list)
    items: list[dict[str, object]] = []
    for item in parsed:
        assert isinstance(item, dict)
        typed: dict[str, object] = {}
        for key, value in item.items():
            assert isinstance(key, str)
            typed[key] = value
        items.append(typed)
    return items


def _text(relative: str) -> str:
    """Read one owned script as text."""
    return (ROOT / relative).read_text(encoding="utf-8")


def _widget(relative: str) -> list[str]:
    """Execute a widget directly when it is executable, otherwise via its shebang."""
    path = ROOT / relative
    if path.stat().st_mode & 0o111:
        return [str(path)]
    first = path.read_text(encoding="utf-8").splitlines()[0]
    if "bash" in first:
        return [_executable("bash"), str(path)]
    return ["/bin/sh", str(path)]


def _install(directory: Path, name: str, body: str) -> None:
    """Install one fake command inside a temporary directory."""
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)


def _fixture_env(bin_dir: Path, home: Path) -> dict[str, str]:
    """Minimal environment: fake arc/python first, then the system shell tools."""
    return {
        "PATH": str(bin_dir) + os.pathsep + "/usr/bin" + os.pathsep + "/bin",
        "HOME": str(home),
        "TMPDIR": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "ARC_ARGS": str(home / "arc-args"),
        "PYTHON_LOG": str(home / "python.log"),
    }


def _assert_ok(result: subprocess.CompletedProcess[str]) -> None:
    """Surface fixture stderr when a widget does not exit 0."""
    assert result.returncode == SUCCESS_EXIT, result.stderr


def test_clean_scripts_match_quality_shellcheck() -> None:
    """Seven owned scripts are clean under --norc and every optional check."""
    result = _run(
        [
            _executable("shellcheck"),
            "--norc",
            "--enable=all",
            "--format=json",
            *[str(ROOT / relative) for relative in CLEAN_SHELL],
        ],
        env=_shell_env(),
        cwd=ROOT,
    )
    assert result.returncode == SUCCESS_EXIT
    assert result.stdout.strip() == "[]"


def test_nightnode_parser_passes_shellcheck_without_dynamic_source() -> None:
    """The config parser is static and does not hide a ShellCheck finding."""
    result = _run(
        [
            _executable("shellcheck"),
            "--norc",
            "--enable=all",
            "--format=json",
            str(ROOT / NIGHTNODE),
        ],
        env=_shell_env(),
        cwd=ROOT,
    )
    assert result.returncode == SUCCESS_EXIT
    assert _items(result.stdout) == []
    source = _text(NIGHTNODE)
    assert 'source "${CONFIG_FILE}"' not in source
    assert 'export "${key}=${value}"' in source


def test_nightnode_config_loads_values_without_executing_them() -> None:
    """Documented KEY=VALUE entries load while shell syntax stays inert."""
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        config_dir = home / "config"
        config_dir.mkdir()
        marker = home / "executed"
        (config_dir / "config.env").write_text(
            "\n".join(
                (
                    "  # comments may be indented",
                    " NIGHTNODE_ALLOW_JOIN =1",
                    "K3S_URL=https://k3s.example.invalid:6443",
                    f"NIGHTNODE_NAME=$(touch {marker})",
                    "",
                )
            ),
            encoding="utf-8",
        )
        bin_dir = home / "bin"
        bin_dir.mkdir()
        _install(
            bin_dir,
            "limactl",
            """#!/bin/sh
if [ "$1" = list ]; then
  printf '%s\n' "$NIGHTNODE_NAME Stopped"
fi
""",
        )
        env = _fixture_env(bin_dir, home)
        env["NIGHTNODE_CONFIG_DIR"] = str(config_dir)
        result = _run([*_widget(NIGHTNODE), "status"], env=env, cwd=ROOT)
        _assert_ok(result)
        assert "join: allowed (https://k3s.example.invalid:6443)" in result.stdout
        assert not marker.exists()


def test_nightnode_config_rejects_malformed_or_invalid_keys() -> None:
    """Malformed lines and non-identifiers fail closed before command calls."""
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        config_dir = home / "config"
        config_dir.mkdir()
        bin_dir = home / "bin"
        bin_dir.mkdir()
        _install(bin_dir, "limactl", "#!/bin/sh\nexit 99\n")
        env = _fixture_env(bin_dir, home)
        env["NIGHTNODE_CONFIG_DIR"] = str(config_dir)
        for entry, message in (
            ("NIGHTNODE_ALLOW_JOIN", "config line is not KEY=VALUE"),
            ("NIGHTNODE-ALLOW_JOIN=1", "config key is not a shell identifier"),
        ):
            (config_dir / "config.env").write_text(entry + "\n", encoding="utf-8")
            result = _run([*_widget(NIGHTNODE), "status"], env=env, cwd=ROOT)
            assert result.returncode == 1
            assert message in result.stderr


def test_owned_scripts_pass_syntax_check_without_executing() -> None:
    """Bash -n and sh -n parse the original dialect and do not run the scripts."""
    bash = _executable("bash")
    env = _shell_env()
    for relative in (*CLEAN_SHELL, NIGHTNODE):
        first = _text(relative).splitlines()[0]
        if first.startswith("#!") and "bash" not in first:
            result = _run(["/bin/sh", "-n", str(ROOT / relative)], env=env, cwd=ROOT)
        else:
            result = _run([bash, "-n", str(ROOT / relative)], env=env, cwd=ROOT)
        assert result.returncode == SUCCESS_EXIT, relative


def test_owned_scripts_do_not_add_a_shell_directive() -> None:
    """Strict mode stays enabled; the remaining dynamic source is not hidden."""
    tool = "shell" + "check"
    action = "dis" + "able"
    for relative in (*CLEAN_SHELL, NIGHTNODE):
        for line in _text(relative).splitlines():
            assert tool not in line or action not in line


def test_guard_drop_rule_stays_braced_and_fail_closed() -> None:
    """The owned chain still ends in DROP and the script still has no ignore."""
    source = _text(GUARD)
    assert '-A "${CHAIN}" -j DROP' in source
    assert "-t mangle -I PREROUTING 1 -i wg-socrat -s 10.250.0.41/32" in source
    assert "--sport 22 -m conntrack --ctstate ESTABLISHED" in source
    assert "-d 10.250.0.40/32" in source
    assert "STOP: bootstrap guard differs from owned rules" in source
    assert "|| true" not in source
    assert "|| exit 0" not in source
    for bad in ("iptables-restore", " -F ", " -P ", "MASQUERADE", "--dport 6443"):
        assert bad not in source


def test_status_paths_do_not_gain_true_ignores() -> None:
    """Existing pkill and kubectl ignores stay; vm_status no longer hides its status."""
    caffeine = _text(CAFFEINE)
    nightnode = _text(NIGHTNODE)
    assert caffeine.count("|| true") == CAFFEINE_IGNORES
    assert 'pkill -u "${UID}" -SIGRTMIN+"${WAYBAR_SIGNAL}" waybar 2>/dev/null || true' in caffeine
    assert 'pkill -u "${UID}" -x hypridle 2>/dev/null || true' in caffeine
    assert STATUS_ENABLED in caffeine
    assert STATUS_DISABLED in caffeine
    assert STATUS_PARTIAL in caffeine
    assert "if is_enabled" not in caffeine
    assert "if lid_is_inhibited" not in caffeine
    assert nightnode.count("|| true") == NIGHTNODE_IGNORES
    assert "vm_status || true" not in nightnode
    assert 'kubectl cordon "${NAME}" || true' in nightnode
    assert "kubectl drain " in nightnode
    assert 'kubectl delete node "${NAME}" --wait=false || true' in nightnode
    assert "2>/dev/null || true)" in nightnode
    assert "< <(" not in nightnode
    for relative in WIDGETS:
        assert "|| true" not in _text(relative)
        assert "set -e" not in _text(relative)


def test_widget_continuations_remain_explicit() -> None:
    """Missing arc metadata, lock contention, and a failed status snapshot still exit 0."""
    refresh = _text(REFRESH)
    assert refresh.startswith("#!/bin/sh\n")
    assert '[ -n "${root}" ] && [ -n "${base}" ] || exit 0' in refresh
    assert 'mkdir "${lock}" 2>/dev/null || exit 0' in refresh
    assert 'cd "${root}" 2>/dev/null || exit 0' in refresh
    for relative in (DOTS, METRICS, STATUS):
        assert "arc info >/dev/null 2>&1 || exit 0" in _text(relative)
    assert "sb=$(arc status -sb 2>/dev/null) || exit 0" in _text(STATUS)
    assert _text(STATUS).count("*) ;;") == STATUS_DEFAULT_ARMS
    toggle = _text(TOGGLE)
    assert toggle.count('[[ -f "${STATE_FILE}" ]]') == TOGGLE_FILE_TESTS
    assert "sed -i --follow-symlinks" in toggle
    assert "no_screen_share" in toggle


def test_arc_metrics_formats_counts_and_keeps_failed_diff_stdout() -> None:
    """A failed arc diff that still printed a stat line formats the same counters."""
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        bin_dir = home / "bin"
        bin_dir.mkdir()
        _install(bin_dir, "arc", ARC)
        env = _fixture_env(bin_dir, home)
        env["ARC_INFO_TEXT"] = "branch: trunk"
        env["ARC_DIFF_RC"] = "1"
        env["ARC_DIFF_TEXT"] = "1 file changed, 4 insertions(+), 2 deletions(-)"
        result = _run(_widget(METRICS), env=env, cwd=home)
        _assert_ok(result)
        assert result.stdout == f"{GREEN}+4{RESET} {RED}-2{RESET} "


def test_arc_metrics_exits_quietly_without_a_repository_or_changes() -> None:
    """Arc info failure and a diff with no changed line are the original quiet exits."""
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        bin_dir = home / "bin"
        bin_dir.mkdir()
        _install(bin_dir, "arc", ARC)
        missing = _fixture_env(bin_dir, home)
        missing["ARC_INFO_RC"] = "1"
        absent = _run(_widget(METRICS), env=missing, cwd=home)
        _assert_ok(absent)
        assert absent.stdout == ""
        clean = _fixture_env(bin_dir, home)
        clean["ARC_INFO_TEXT"] = "branch: trunk"
        clean["ARC_DIFF_TEXT"] = "clean working tree"
        unchanged = _run(_widget(METRICS), env=clean, cwd=home)
        _assert_ok(unchanged)
        assert unchanged.stdout == ""


def test_arc_dots_uses_remote_head_and_counts_failed_log_stdout() -> None:
    """Missing remote_head falls back to trunk; a failing log still contributes its lines."""
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        bin_dir = home / "bin"
        bin_dir.mkdir()
        _install(bin_dir, "arc", ARC)
        ahead = _fixture_env(bin_dir, home)
        ahead["ARC_INFO_TEXT"] = "branch: trunk"
        ahead["ARC_LOG_RC"] = "1"
        ahead["ARC_LOG_TEXT"] = "one\ntwo\nthree"
        result = _run([*_widget(DOTS), "ahead"], env=ahead, cwd=home)
        _assert_ok(result)
        assert result.stdout == AHEAD * 3
        logged = (home / "arc-args").read_text(encoding="utf-8")
        assert "log arcadia/trunk..HEAD --oneline" in logged
        behind = _fixture_env(bin_dir, home)
        behind["ARC_INFO_TEXT"] = "remote_head: origin/feature"
        behind["ARC_LOG_TEXT"] = "only"
        back = _run([*_widget(DOTS), "behind"], env=behind, cwd=home)
        _assert_ok(back)
        assert back.stdout == BEHIND
        assert "log HEAD..origin/feature --oneline" in (home / "arc-args").read_text(
            encoding="utf-8"
        )


def test_arc_dots_zero_and_unknown_requests_exit_zero() -> None:
    """Grep -c returning 1 for zero lines does not fail the widget, nor does an unknown side."""
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        bin_dir = home / "bin"
        bin_dir.mkdir()
        _install(bin_dir, "arc", ARC)
        empty = _fixture_env(bin_dir, home)
        empty["ARC_INFO_TEXT"] = "branch: trunk"
        empty["ARC_LOG_RC"] = "1"
        empty["ARC_LOG_TEXT"] = ""
        quiet = _run([*_widget(DOTS), "ahead"], env=empty, cwd=home)
        _assert_ok(quiet)
        assert quiet.stdout == ""
        unknown = _run([*_widget(DOTS), "sideways"], env=empty, cwd=home)
        _assert_ok(unknown)
        assert unknown.stdout == ""
        args = home / "arc-args"
        args.unlink()
        missing = _fixture_env(bin_dir, home)
        missing["ARC_INFO_RC"] = "1"
        absent = _run([*_widget(DOTS), "ahead"], env=missing, cwd=home)
        _assert_ok(absent)
        assert absent.stdout == ""
        assert "log " not in args.read_text(encoding="utf-8")


def test_arc_status_counts_lines_and_discards_a_failed_snapshot() -> None:
    """Unknown status codes still count; a non-zero status snapshot exits 0 with no symbol."""
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        bin_dir = home / "bin"
        bin_dir.mkdir()
        _install(bin_dir, "arc", ARC)
        counted = _fixture_env(bin_dir, home)
        counted["ARC_INFO_TEXT"] = "branch: trunk"
        counted["ARC_STATUS_TEXT"] = "## main\n M file\nXX mystery\n?? other"
        counted["ARC_STASH_TEXT"] = "stash@{0}: wip"
        result = _run(_widget(STATUS), env=counted, cwd=home)
        _assert_ok(result)
        assert result.stdout == f"{STATUS_MARK} 3 📦 "
        failed = _fixture_env(bin_dir, home)
        failed["ARC_INFO_TEXT"] = "branch: trunk"
        failed["ARC_STATUS_RC"] = "1"
        failed["ARC_STATUS_TEXT"] = " M file"
        discarded = _run(_widget(STATUS), env=failed, cwd=home)
        _assert_ok(discarded)
        assert discarded.stdout == ""


def _prepared_refresh(home: Path) -> tuple[dict[str, str], Path, Path, Path]:
    """Install fake arc/python and the real widget helpers under a temporary HOME."""
    bin_dir = home / "bin"
    bin_dir.mkdir()
    _install(bin_dir, "arc", ARC)
    _install(bin_dir, "python3", PYTHON)
    starship = home / ".config" / "starship"
    starship.mkdir(parents=True)
    for name in ("arc_state.sh", "arc_status.sh", "arc_metrics.sh", "arc_dots.sh"):
        target = starship / name
        shutil.copyfile(ROOT / "ansible/roles/starship/files" / name, target)
        target.chmod(0o700)
    root = home / "repo"
    root.mkdir()
    base = home / "segments" / "arc"
    base.parent.mkdir()
    env = _fixture_env(bin_dir, home)
    env["ARC_INFO_TEXT"] = "branch: feature\nremote_head: origin/feature"
    env["ARC_STATUS_TEXT"] = " M file"
    env["ARC_DIFF_TEXT"] = "1 file changed, 2 insertions(+), 1 deletion(-)"
    env["ARC_LOG_TEXT"] = "commit"
    return env, root, base, starship


def test_arc_refresh_held_lock_exits_without_writing() -> None:
    """An existing lock directory is left in place and no segment file is created."""
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        env, root, base, _starship = _prepared_refresh(home)
        held = Path(str(base) + ".lock")
        held.mkdir()
        blocked = _run([*_widget(REFRESH), str(root), str(base)], env=env, cwd=home)
        _assert_ok(blocked)
        assert held.is_dir()
        assert not Path(str(base) + ".branch").exists()


def test_arc_refresh_keeps_partial_helper_stdout_and_later_segments() -> None:
    """A helper that exits 1 still contributes its stdout, and later segments are written."""
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        env, root, base, starship = _prepared_refresh(home)
        state = starship / "arc_state.sh"
        state.write_text("#!/bin/sh\nprintf '%s\\n' PARTIAL\nexit 1\n", encoding="utf-8")
        state.chmod(0o700)
        refreshed = _run([*_widget(REFRESH), str(root), str(base)], env=env, cwd=home)
        _assert_ok(refreshed)
        assert (Path(str(base) + ".branch")).read_text(encoding="utf-8") == "feature"
        assert (Path(str(base) + ".state")).read_text(encoding="utf-8") == "PARTIAL"
        assert (Path(str(base) + ".status")).read_text(encoding="utf-8") == f"{STATUS_MARK} 1 "
        assert (Path(str(base) + ".metrics")).read_text(encoding="utf-8") == (
            f"{GREEN}+2{RESET} {RED}-1{RESET} "
        )
        assert (Path(str(base) + ".ahead")).read_text(encoding="utf-8") == AHEAD
        assert (Path(str(base) + ".behind")).read_text(encoding="utf-8") == BEHIND
        assert not Path(str(base) + ".lock").exists()
        python_log = (home / "python.log").read_text(encoding="utf-8")
        assert "refresh" in python_log
        assert "feature" in python_log


def test_arc_refresh_missing_args_and_bad_directory_exit_zero() -> None:
    """Missing arguments and a non-directory root are the original quiet exits."""
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        env, _root, _base, _starship = _prepared_refresh(home)
        missing = _run([*_widget(REFRESH)], env=env, cwd=home)
        _assert_ok(missing)
        not_dir = home / "not-a-directory"
        not_dir.write_text("x", encoding="utf-8")
        other = home / "other" / "arc"
        other.parent.mkdir()
        failed_cd = _run([*_widget(REFRESH), str(not_dir), str(other)], env=env, cwd=home)
        _assert_ok(failed_cd)
        assert not Path(str(other) + ".branch").exists()
        assert not Path(str(other) + ".lock").exists()
