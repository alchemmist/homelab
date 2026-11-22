"""Offline checks for the HOME/NL UDP echo predicate; no sockets are opened."""

import ast
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "udp_probe", ROOT / "ci/vpn/vpn-home-nl-udp-probe.py"
)
assert spec is not None
assert spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def _signature(node: ast.AST) -> str:
    """Compare complete executable syntax independently of quotes and spacing."""
    return ast.dump(node, include_attributes=False)


def _bounded_echo_contract(source: str) -> None:
    """Require a live timeout guard and exactly one validated echo in the loop."""
    module = ast.parse(source)
    servers = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "server"]
    assert len(servers) == 1
    server = servers[0]
    bound = _signature(ast.parse("assert 1 <= timeout <= 45").body[0])
    bounds = [n for n in server.body if _signature(n) == bound]
    assert len(bounds) == 1
    sockets = [n for n in server.body if isinstance(n, ast.With)]
    assert len(sockets) == 1
    assert server.body.index(bounds[0]) < server.body.index(sockets[0])
    loops = [n for n in sockets[0].body if isinstance(n, ast.While)]
    assert len(loops) == 1
    expected = ast.parse(
        "if valid(data, peer):\n"
        "    s.sendto(data, peer)\n"
        "    return {'received_home_datagram': True, 'bytes': len(data), 'port': PORT}\n"
    ).body[0]
    guards = [n for n in loops[0].body if _signature(n) == _signature(expected)]
    assert len(guards) == 1
    guard = guards[0]
    assert isinstance(guard, ast.If)
    send = guard.body[0]
    assert isinstance(send, ast.Expr)
    sends = [
        n
        for n in ast.walk(server)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "sendto"
    ]
    assert sends == [send.value]


def test_only_small_exact_shape_from_home_gets_echoed() -> None:
    """Accept only a 16-byte payload from HOME with the fixed prefix."""
    valid = m.PREFIX + b"x" * 16
    assert m.valid(valid, (m.HOME, 51843))
    assert not m.valid(valid, ("91.189.82.238", 51843))
    assert not m.valid(valid + b"x", (m.HOME, 51843))
    assert not m.valid(b"bad" + b"x" * 100, (m.HOME, 51843))


def test_bounded_no_reuse_or_network_state_mutation() -> None:
    """Require a bounded diagnostic that does not mutate routes, firewalls, or VPN state."""
    s = (ROOT / "ci/vpn/vpn-home-nl-udp-probe.py").read_text()
    _bounded_echo_contract(s)
    assert "setsockopt" not in s
    for forbidden in ["subprocess", "wg set", "nft", "iptables", "sudo"]:
        assert forbidden not in s


@pytest.mark.parametrize(
    ("needle", "replacement"),
    [
        ("assert 1 <= timeout <= 45", "assert 0 <= timeout <= 45"),
        ("assert 1 <= timeout <= 45", "pass  # assert 1 <= timeout <= 45"),
        ("if valid(data, peer):", "if True:"),
        ("s.sendto(data, peer)", "s.sendto(data, (HOME, PORT))"),
    ],
)
def test_bounded_echo_rejects_guard_mutations(needle: str, replacement: str) -> None:
    """Reject weakened bounds, comment decoys, bypassed validation and retargeted echo."""
    source = (ROOT / "ci/vpn/vpn-home-nl-udp-probe.py").read_text()
    assert source.count(needle) == 1
    with pytest.raises(AssertionError):
        _bounded_echo_contract(source.replace(needle, replacement, 1))


def test_predicate_and_source_checks_never_open_sockets() -> None:
    """Exercise both original contracts with socket construction forbidden."""
    with patch("socket.socket", side_effect=AssertionError("socket forbidden")) as socket:
        test_only_small_exact_shape_from_home_gets_echoed()
        test_bounded_no_reuse_or_network_state_mutation()
    socket.assert_not_called()
