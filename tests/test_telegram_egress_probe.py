"""Exercise probe errors without sending a packet."""

import contextlib
import runpy
import socket
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

samples = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/telegram-egress-probe.py")
)["samples"]


def test_dns_error() -> None:
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("resolver", 3)):
        assert list(samples("example.com", None))[0]["stage"] == "dns"


def test_tcp_and_tls_are_distinct() -> None:
    address = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))
    with (
        patch.dict(samples.__globals__, {"resolve": lambda host: [address, address]}),
        patch("socket.socket") as ctor,
    ):
        sock = ctor.return_value.__enter__.return_value
        ctx = MagicMock()
        sock.connect.side_effect = TimeoutError
        (row,) = samples("example.com", ctx)
        assert row["stage"] == "tcp"
        assert "tls_ms" not in row
        ctx.wrap_socket.assert_not_called()
        sock.connect.side_effect = None
        ctx.wrap_socket.side_effect = TimeoutError
        (row,) = samples("example.com", ctx)
        assert row["stage"] == "tls"
        assert "tcp_ms" in row
        assert "tls_ms" in row
        ctx.wrap_socket.assert_called_with(sock, server_hostname="example.com")
        ctx.wrap_socket.reset_mock()
        ctx.wrap_socket.side_effect = None
        (row,) = samples("example.com", ctx)
        assert row["stage"] == "ok"
        ctx.wrap_socket.assert_called_once_with(sock, server_hostname="example.com")


def test_malformed_resolver_output() -> None:
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=b"[")):
        assert list(samples("example.com", None))[0]["stage"] == "dns"


def test_each_distinct_address_is_sampled() -> None:
    targets = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ("192.0.2.1", "192.0.2.2")
    ]
    with (
        patch.dict(samples.__globals__, {"resolve": lambda host: targets}),
        patch("socket.socket"),
    ):
        assert [r["ip"] for r in samples("example.com", MagicMock())] == [
            "192.0.2.1",
            "192.0.2.2",
        ]


def test_periodic_chart_isolated_and_bounded() -> None:
    """Only the probe shares the bot network; it gets no bot credentials or ports."""
    import subprocess

    import yaml

    root = Path(__file__).resolve().parents[1]
    args = [
        "helm",
        "template",
        "socrat-bot",
        str(root / "charts/socrat-bot"),
        "-f",
        str(root / "deploy/socrat-bot/values.yaml"),
    ]
    manifests = list(yaml.safe_load_all(subprocess.check_output(args, text=True)))
    specs = {
        d["metadata"]["name"]: d["spec"]["template"]["spec"]
        for d in manifests
        if d and d["kind"] == "Deployment"
    }
    for name in ("socrat-bot", "socrat-telegram-path-control"):
        spec = specs[name]
        probe = next(c for c in spec["containers"] if c["name"] == "telegram-path")
        assert not {"env", "envFrom", "ports"} & probe.keys()
        assert {v["name"] for v in probe["volumeMounts"]} == {
            "probe-code",
            "probe-samples",
        }
        assert spec["automountServiceAccountToken"] is False
        volume = next(v for v in spec["volumes"] if v["name"] == "probe-samples")
        assert volume["emptyDir"] == {"medium": "Memory", "sizeLimit": "4Mi"}
    bot = specs["socrat-bot"]
    assert not bot.get("hostNetwork")
    assert bot["hostAliases"] == [{"ip": "10.43.0.213", "hostnames": ["api.telegram.org"]}]
    term = bot["affinity"]["podAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"][0][
        "podAffinityTerm"
    ]
    assert term["namespaces"] == ["postgres"]
    assert term["labelSelector"]["matchLabels"]["cnpg.io/instanceRole"] == "primary"
    relay = specs["socrat-telegram-relay"]
    assert relay["nodeSelector"]["kubernetes.io/hostname"] == "socrat-1"
    assert bot["nodeSelector"]["kubernetes.io/hostname"] == "socrat-1"
    assert not relay["automountServiceAccountToken"]
    stream = next(c for c in relay["containers"] if c["name"] == "stream")
    assert "env" not in stream and "envFrom" not in stream
    assert (
        specs["socrat-telegram-path-control"]["nodeSelector"]["kubernetes.io/hostname"]
        == "socrat-3"
    )


def test_periodic_retains_last_120_batches(tmp_path) -> None:
    """No network, sleeps or pod runtime required."""
    import json

    rows = iter(range(121))
    periodic = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/telegram-egress-probe.py")
    )["periodic"]
    with (
        patch.dict(
            periodic.__globals__,
            {
                "Path": lambda _: tmp_path / "recent.json",
                "batch": lambda _: next(rows),
                "sleep": lambda _: None,
            },
        ),
        contextlib.suppress(StopIteration),
    ):
        periodic(None)
    assert json.loads((tmp_path / "recent.json").read_text()) == list(range(1, 121))


def test_streamable_probe_matches_helm_payload() -> None:
    """The standalone stdin entrypoint and chart payload must remain byte-identical."""
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts/telegram-egress-probe.py").read_bytes() == (
        root / "charts/socrat-bot/files/telegram-egress-probe.py"
    ).read_bytes()


def test_overrun_skips_ticks_and_transient_write_failure_recovers(tmp_path) -> None:
    import json

    periodic = samples.__globals__["periodic"]
    rows = iter([1, 2])
    ticks = iter([0, 38, 60, 65, 90])
    waits = []
    write = Path.write_text

    def flaky_write(path, data):
        if not waits:
            msg = "simulated transient failure"
            raise OSError(msg)
        return write(path, data)

    with (
        patch.object(Path, "write_text", flaky_write),
        patch.dict(
            periodic.__globals__,
            {
                "Path": lambda _: tmp_path / "recent.json",
                "batch": lambda _: next(rows),
                "monotonic": lambda: next(ticks),
                "sleep": waits.append,
            },
        ),
        contextlib.suppress(StopIteration),
    ):
        periodic(None)
    assert waits == [22, 25]
    assert json.loads((tmp_path / "recent.json").read_text()) == [1, 2]
