"""Static ShellCheck regressions and isolated fixtures for one owned shell batch."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFUSAL_EXIT = 2
SUCCESS_EXIT = 0
WAIT_SECONDS = 2
POLL_SECONDS = 3
TOOL_TIMEOUT_SECONDS = 15
FIXED_SHELL = (
    "ansible/files/socrat-sudo",
    "ansible/roles/debian_laptop/files/sway/homelab-sway-menu",
    "ansible/roles/desktop_panel/files/paru_updates.sh",
    "ansible/roles/desktop_panel/files/pacman_updates.sh",
    "ansible/roles/desktop_environment/files/layout-listener.sh",
    "ansible/roles/desktop_panel/files/battery-degradation.sh",
    "ansible/roles/starship/files/arc_state.sh",
    "services/spi-tokenizer/build-local.sh",
    "ansible/roles/wiki_editor_client/files/wiki-editor-resolver.sh",
    "scripts/rustfs/deploy.sh",
)
USAGE = "Usage: deploy.sh --apply <independently-approved-HEAD> <private-runtime-values.yaml>"
YELLOW = "\033[33m"
RESET = "\033[0m"
BATTERY = ROOT / "ansible/roles/desktop_panel/files/battery-degradation.sh"
MENU = ROOT / "ansible/roles/debian_laptop/files/sway/homelab-sway-menu"
ARC_STATE = ROOT / "ansible/roles/starship/files/arc_state.sh"
BUILD_LOCAL = ROOT / "services/spi-tokenizer/build-local.sh"
DEPLOY = ROOT / "scripts/rustfs/deploy.sh"
SUDO = ROOT / "ansible/files/socrat-sudo"
HISTORICAL_BATTERY = """
echo "(1 - $(upower -i $(upower -e | grep BAT) | awk '\
        /energy-full:/ {ef=$2}\
        /energy-full-design:/ {efd=$2}\
        END {print ef/efd}')) * 100 + 0.5" | bc | cut -d'.' -f1
"""


def _executable(name: str) -> str:
    """Return an absolute tool path from PATH."""
    found = shutil.which(name)
    if found is None:
        message = "required executable is not on PATH"
        raise RuntimeError(message)
    return found


def _start(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    """Start one allowlisted fixture or static checker."""
    return subprocess.Popen(
        argv,
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _run(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one allowlisted fixture or static checker to completion."""
    proc = _start(argv, env=env)
    try:
        stdout, stderr = proc.communicate(timeout=TOOL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _stop(proc)
        stdout, stderr = proc.communicate()
        return subprocess.CompletedProcess(argv, proc.returncode or 1, stdout, stderr)
    return subprocess.CompletedProcess(argv, proc.returncode or 0, stdout, stderr)


def _path_env(bin_dir: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """Prepend a fixture directory without dropping the rest of PATH."""
    env = dict(os.environ if base is None else base)
    current = env.get("PATH", "")
    env["PATH"] = str(bin_dir) + (os.pathsep + current if current else "")
    return env


def _write_exec(directory: Path, name: str, body: str) -> Path:
    """Install one fake command inside a temporary directory."""
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)
    return path


def _argv(relative: str) -> list[str]:
    """Execute preserved mode: direct for +x, interpreter for source-only scripts."""
    path = ROOT / relative
    if path.stat().st_mode & 0o111:
        return [str(path)]
    first = path.read_text(encoding="utf-8").splitlines()[0]
    if "bash" in first:
        return [_executable("bash"), str(path)]
    return ["/bin/sh", str(path)]


def _stop(proc: subprocess.Popen[str]) -> None:
    """Stop a fixture process group after the lines under test have been read."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=WAIT_SECONDS)


def _captured(proc: subprocess.Popen[str]) -> str:
    """Read two stdout lines from a looping widget, then stop it."""
    stdout = proc.stdout
    if stdout is None:
        message = "stdout was not captured"
        raise RuntimeError(message)
    try:
        return stdout.readline() + stdout.readline()
    finally:
        _stop(proc)


def test_fixed_scripts_match_quality_shellcheck() -> None:
    """Use the quality adapter flags: --norc and every optional check."""
    result = _run(
        [
            _executable("shellcheck"),
            "--norc",
            "--enable=all",
            "--format=json",
            *[str(ROOT / relative) for relative in FIXED_SHELL],
        ],
    )
    assert result.returncode == SUCCESS_EXIT
    assert result.stdout.strip() == "[]"


def test_fixed_scripts_pass_bash_syntax() -> None:
    """Bash -n is static and does not execute the scripts."""
    bash = _executable("bash")
    for relative in FIXED_SHELL:
        result = _run([bash, "-n", str(ROOT / relative)])
        assert result.returncode == SUCCESS_EXIT, relative


def test_fixed_scripts_do_not_add_a_shell_directive() -> None:
    """Strict mode stays enabled; findings are not hidden."""
    tool = "shell" + "check"
    action = "dis" + "able"
    for relative in FIXED_SHELL:
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
            assert tool not in line or action not in line


def test_socrat_sudo_prepends_library_without_dropping_arguments() -> None:
    """PYTHONPATH gains /usr/local/lib only when an existing value is non-empty."""
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        _write_exec(
            directory,
            "python3",
            "#!/bin/sh\nprintf 'PYTHONPATH=%s\\n' \"${PYTHONPATH-unset}\"\nprintf '%s\\n' \"$@\"\n",
        )
        unset = _path_env(directory)
        unset.pop("PYTHONPATH", None)
        empty = _path_env(directory)
        empty["PYTHONPATH"] = ""
        extended = _path_env(directory)
        extended["PYTHONPATH"] = "/opt/existing"
        for env, expected in (
            (unset, "/usr/local/lib"),
            (empty, "/usr/local/lib"),
            (extended, "/usr/local/lib:/opt/existing"),
        ):
            result = _run([str(SUDO), "--check", "arg"], env=env)
            assert result.returncode == SUCCESS_EXIT
            assert result.stdout.splitlines() == [
                f"PYTHONPATH={expected}",
                "-m",
                "socrat_sudo",
                "--check",
                "arg",
            ]


def _menu_result(directory: Path, choice: str, *, fail: bool) -> subprocess.CompletedProcess[str]:
    """Run a copy of the menu whose external programs are fixture binaries."""
    log = directory / "commands"
    if log.exists():
        log.unlink()
    if fail:
        wofi_body = "#!/bin/sh\nexit 1\n"
    else:
        wofi_body = "#!/bin/sh\nprintf '%s\\n' " + shlex.quote(choice) + "\n"
    wofi = _write_exec(directory, "wofi", wofi_body)
    app = _write_exec(
        directory,
        "app",
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "${FIXTURE_LOG:?}"\n',
    )
    other = _write_exec(
        directory,
        "other",
        '#!/bin/sh\nprintf \'other %s\\n\' "$*" >> "${FIXTURE_LOG:?}"\n',
    )
    text = MENU.read_text(encoding="utf-8")
    for original, target in (
        ("/usr/local/bin/homelab-sway-app", app),
        ("/usr/local/bin/homelab-sway-window-action", other),
        ("/usr/bin/pavucontrol", other),
        ("/usr/bin/nm-connection-editor", other),
        ("/usr/bin/wofi", wofi),
    ):
        text = text.replace(original, shlex.quote(str(target)))
    script = directory / "menu"
    script.write_text(text, encoding="utf-8")
    env = _path_env(directory)
    env["FIXTURE_LOG"] = str(log)
    return _run(["/bin/sh", str(script)], env=env)


def test_sway_menu_keeps_known_choice_and_unknown_exit() -> None:
    """A known entry still execs; an unknown entry and a closed menu exit 0."""
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        chosen = _menu_result(directory, "\u0411\u0440\u0430\u0443\u0437\u0435\u0440", fail=False)
        assert chosen.returncode == SUCCESS_EXIT
        assert (directory / "commands").read_text(encoding="utf-8") == "browser\n"
        unknown = _menu_result(directory, "not-a-menu-item", fail=False)
        assert unknown.returncode == SUCCESS_EXIT
        assert not (directory / "commands").exists()
        closed = _menu_result(directory, "", fail=True)
        assert closed.returncode == SUCCESS_EXIT
        assert not (directory / "commands").exists()


def test_update_counters_keep_initial_zero_then_package_lines() -> None:
    """Waybar still receives the initial zero before the first package count."""
    cases = (
        ("ansible/roles/desktop_panel/files/paru_updates.sh", "paru", 2),
        ("ansible/roles/desktop_panel/files/pacman_updates.sh", "checkupdates", 1),
    )
    for relative, command, packages in cases:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            lines = "".join(f"printf '%s\\n' 'pkg{index}'\n" for index in range(packages))
            _write_exec(directory, command, "#!/bin/sh\n" + lines)
            _write_exec(directory, "sleep", "#!/bin/sh\nexit 0\n")
            proc = _start(_argv(relative), env=_path_env(directory))
            output = _captured(proc)
            first, second = output.splitlines()
            assert first == "0"
            assert int(second.strip()) == packages


def test_layout_listener_signals_waybar_when_keymap_changes() -> None:
    """The real-time signal identity stays SIGRTMIN+5 for Waybar."""
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        log = directory / "signals"
        _write_exec(directory, "hyprctl", "#!/bin/sh\nprintf '%s\\n' '{}'\n")
        _write_exec(
            directory,
            "jq",
            "#!/bin/sh\ncat >/dev/null\nprintf '%s\\n' 'English'\n",
        )
        _write_exec(
            directory,
            "pkill",
            '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "${FIXTURE_LOG:?}"\n',
        )
        _write_exec(directory, "sleep", "#!/bin/sh\nexec /bin/sleep 30\n")
        env = _path_env(directory)
        env["FIXTURE_LOG"] = str(log)
        proc = _start(
            _argv("ansible/roles/desktop_environment/files/layout-listener.sh"),
            env=env,
        )
        try:
            deadline = time.monotonic() + POLL_SECONDS
            seen = ""
            while time.monotonic() < deadline:
                if log.exists():
                    seen = log.read_text(encoding="utf-8")
                    if seen:
                        break
                time.sleep(0.05)
        finally:
            _stop(proc)
        assert seen == "-SIGRTMIN+5 waybar\n"


def _upower(directory: Path) -> Path:
    """Fake upower that records each argument without splitting on spaces."""
    return _write_exec(
        directory,
        "upower",
        """#!/bin/sh
printf 'argc %s\n' "$#" >> "${FIXTURE_LOG:?}"
index=1
for argument in "$@"; do
  printf 'arg %s %s\n' "$index" "$argument" >> "${FIXTURE_LOG:?}"
  index=$((index + 1))
done
if [ "$1" = "-e" ]; then
  printf '%s\n' "${FIXTURE_DEVICES:?}"
  exit 0
fi
if [ "$1" = "-i" ]; then
  printf '%s\n' 'energy-full: 50' 'energy-full-design: 100'
  exit 0
fi
exit 1
""",
    )


def _battery_output(devices: str) -> tuple[str, str]:
    """Return current stdout and the upower argument log for one device list."""
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        log = directory / "upower.log"
        _upower(directory)
        env = _path_env(directory)
        env["FIXTURE_LOG"] = str(log)
        env["FIXTURE_DEVICES"] = devices
        result = _run(_argv(str(BATTERY.relative_to(ROOT))), env=env)
        assert result.returncode == SUCCESS_EXIT
        return result.stdout, log.read_text(encoding="utf-8")


def test_battery_preserves_output_and_passes_one_device_path() -> None:
    """A normal path matches the old pipeline; a spaced path is one argument."""
    simple_out, simple_log = _battery_output(
        "/org/freedesktop/UPower/devices/battery_BAT0",
    )
    spaced_out, spaced_log = _battery_output(
        "/org/freedesktop/UPower/devices/battery BAT0",
    )
    absent_out, absent_log = _battery_output(
        "/org/freedesktop/UPower/devices/line_power_AC",
    )
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        log = directory / "oracle.log"
        _upower(directory)
        env = _path_env(directory)
        env["FIXTURE_LOG"] = str(log)
        env["FIXTURE_DEVICES"] = "/org/freedesktop/UPower/devices/battery_BAT0"
        oracle = _run([_executable("bash"), "-c", HISTORICAL_BATTERY], env=env)
    assert oracle.returncode == SUCCESS_EXIT
    assert simple_out == "50\n"
    assert oracle.stdout == simple_out
    assert "arg 2 /org/freedesktop/UPower/devices/battery_BAT0\n" in simple_log
    assert spaced_out == "50\n"
    assert "argc 2\narg 1 -i\narg 2 /org/freedesktop/UPower/devices/battery BAT0\n" in spaced_log
    assert absent_out == "50\n"
    assert "argc 1\narg 1 -i\n" in absent_log


def _arc_symbol(label: str) -> str:
    """Read one sequencer symbol from the script instead of duplicating it."""
    for line in ARC_STATE.read_text(encoding="utf-8").splitlines():
        if label in line and 'sym="' in line:
            return line.split('sym="', 1)[1].split('"', 1)[0]
    message = "sequencer symbol was not found"
    raise RuntimeError(message)


def _arc(directory: Path, *, fail: bool, text: str) -> subprocess.CompletedProcess[str]:
    """Run arc_state against a fake arc binary."""
    _write_exec(
        directory,
        "arc",
        """#!/bin/sh
if [ "${FIXTURE_ARC_FAIL:-}" = 1 ]; then
  exit 1
fi
printf '%s\n' "${FIXTURE_ARC_OUT-}"
""",
    )
    env = _path_env(directory)
    env["FIXTURE_ARC_FAIL"] = "1" if fail else ""
    env["FIXTURE_ARC_OUT"] = text
    return _run(_argv(str(ARC_STATE.relative_to(ROOT))), env=env)


def test_arc_state_preserves_symbol_and_quiet_exit() -> None:
    """Missing arc or an empty sequencer exits 0 without printing a symbol."""
    with tempfile.TemporaryDirectory() as raw:
        failed = _arc(Path(raw), fail=True, text="sequencer: rebase")
    assert failed.returncode == SUCCESS_EXIT
    assert failed.stdout == ""
    with tempfile.TemporaryDirectory() as raw:
        empty = _arc(Path(raw), fail=False, text="branch: main")
    assert empty.returncode == SUCCESS_EXIT
    assert empty.stdout == ""
    with tempfile.TemporaryDirectory() as raw:
        rebase = _arc(Path(raw), fail=False, text="sequencer: rebase")
    assert rebase.returncode == SUCCESS_EXIT
    assert rebase.stdout == f"{YELLOW}{_arc_symbol('rebase)')}{RESET} "
    with tempfile.TemporaryDirectory() as raw:
        picked = _arc(Path(raw), fail=False, text="sequencer: cherry-pick")
    assert picked.stdout == f"{YELLOW}{_arc_symbol('cherry-pick)')}{RESET} "
    with tempfile.TemporaryDirectory() as raw:
        other = _arc(Path(raw), fail=False, text="sequencer: merge")
    assert other.returncode == SUCCESS_EXIT
    assert other.stdout == f"{YELLOW}{_arc_symbol('*)')}{RESET} "


def test_build_local_clears_cdpath_and_keeps_the_usage_guard() -> None:
    """CDPATH='' is an empty assignment, and the required asset argument stays."""
    text = BUILD_LOCAL.read_text(encoding="utf-8")
    assert "set -eu\n" in text
    assert "src=${1:?usage: build-local.sh /private/assets}\n" in text
    assert "CDPATH='' cd --" in text
    result = _run(
        [
            _executable("bash"),
            "-c",
            "bare=$(CDPATH= cd -- /private && pwd)\n"
            "empty=$(CDPATH='' cd -- /private && pwd)\n"
            'printf \'%s\\n%s\\n\' "$bare" "$empty"\n',
        ],
    )
    assert result.returncode == SUCCESS_EXIT
    assert result.stdout == "/private\n/private\n"


def _deploy(
    directory: Path,
    args: list[str],
    extra: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    """Run deploy.sh through fake git and helm. Helm records any invocation."""
    git_log = directory / "git.log"
    helm_log = directory / "helm.log"
    _write_exec(
        directory,
        "git",
        """#!/bin/sh
printf '%s\n' "$*" >> "${FIXTURE_GIT:?}"
shift
shift
cmd=$1
shift
if [ "$cmd" = "${FIXTURE_FAIL:-}" ]; then exit 73; fi
case "$cmd" in
  status)
    if [ -n "${FIXTURE_STATUS:-}" ]; then printf '%s\n' "$FIXTURE_STATUS"; fi
    ;;
  ls-files)
    joined=$(printf '%s ' "$@")
    case "$joined" in
      *--ignored*)
        if [ -n "${FIXTURE_IGNORED:-}" ]; then printf '%s\n' "$FIXTURE_IGNORED"; fi
        ;;
      *)
        if [ -n "${FIXTURE_UNTRACKED:-}" ]; then printf '%s\n' "$FIXTURE_UNTRACKED"; fi
        ;;
    esac
    ;;
  rev-parse)
    printf '%s\n' "${FIXTURE_HEAD:-0123456789abcdef}"
    ;;
esac
exit 0
""",
    )
    _write_exec(
        directory,
        "helm",
        """#!/bin/sh
printf '%s\n' "$*" >> "${FIXTURE_HELM:?}"
exit 99
""",
    )
    env = _path_env(directory)
    env["FIXTURE_GIT"] = str(git_log)
    env["FIXTURE_HELM"] = str(helm_log)
    env.update(extra)
    result = _run([str(DEPLOY), *args], env=env)
    git_text = git_log.read_text(encoding="utf-8") if git_log.exists() else ""
    helm_text = helm_log.read_text(encoding="utf-8") if helm_log.exists() else ""
    return result, git_text, helm_text


def test_deploy_refuses_before_helm() -> None:
    """Dirty, untracked, ignored, and unapproved heads exit 2 without Helm."""
    assert "set -euo pipefail\n" in DEPLOY.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as raw:
        result, git_text, helm_text = _deploy(
            Path(raw),
            [],
            {"FIXTURE_STATUS": "", "FIXTURE_HEAD": "abc"},
        )
    assert result.returncode == REFUSAL_EXIT
    assert result.stderr.strip() == USAGE
    assert "rev-parse" not in git_text
    assert helm_text == ""
    with tempfile.TemporaryDirectory() as raw:
        result, git_text, helm_text = _deploy(
            Path(raw),
            [],
            {"FIXTURE_STATUS": " M charts/rustfs/Chart.yaml"},
        )
    assert result.returncode == REFUSAL_EXIT
    assert result.stderr.strip() == "Refusing dirty tracked source"
    assert "ls-files" not in git_text
    assert helm_text == ""
    with tempfile.TemporaryDirectory() as raw:
        result, git_text, helm_text = _deploy(
            Path(raw),
            [],
            {"FIXTURE_UNTRACKED": "charts/rustfs/local.yaml"},
        )
    assert result.returncode == REFUSAL_EXIT
    assert result.stderr.strip() == "Refusing untracked or ignored chart inputs"
    assert "--ignored" not in git_text
    assert helm_text == ""
    with tempfile.TemporaryDirectory() as raw:
        result, _git_text, helm_text = _deploy(
            Path(raw),
            [],
            {"FIXTURE_IGNORED": "charts/rustfs/secret.yaml"},
        )
    assert result.returncode == REFUSAL_EXIT
    assert result.stderr.strip() == "Refusing untracked or ignored chart inputs"
    assert helm_text == ""
    with tempfile.TemporaryDirectory() as raw:
        result, git_text, helm_text = _deploy(
            Path(raw),
            ["--apply", "not-the-head", "/nonexistent/values.yaml"],
            {"FIXTURE_HEAD": "abc"},
        )
    assert result.returncode == REFUSAL_EXIT
    assert result.stderr.strip() == USAGE
    assert "rev-parse" in git_text
    assert helm_text == ""


def test_deploy_git_failure_refuses_before_any_helm_invocation() -> None:
    """A failing inspection must not turn into an empty successful answer."""
    for command in ("status", "ls-files", "rev-parse"):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            values = directory / "runtime.yaml"
            values.write_text("{}\n", encoding="utf-8")
            result, _git_text, helm_text = _deploy(
                directory,
                ["--apply", "", str(values)],
                {"FIXTURE_FAIL": command},
            )
        assert result.returncode == REFUSAL_EXIT
        assert "Refusing failed source verification:" in result.stderr
        assert helm_text == ""
