"""Verify a WireGuard client tunnel against SSH host keys and DNS checks."""

import argparse
import json
from pathlib import Path
import subprocess
import time

NAMESPACE = "homelab-tim-check"
INTERFACE = "wg-tim-check"
ADDRESSES = ["10.250.0.1", "10.250.0.3", "10.250.0.2", "10.250.0.5"]


def run(*args: str, input: str | None = None, timeout: int = 30) -> str:
    result = subprocess.run(args, input=input, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        detail = "" if args[0] in ("wg", "wg-quick") else ": " + result.stderr.strip()
        raise RuntimeError(f"{args[0]} failed with status {result.returncode}" + detail)
    return result.stdout


def net(*args: str, timeout: int = 30) -> str:
    return run("ip", "netns", "exec", NAMESPACE, *args, timeout=timeout)


def _require_clean_namespace() -> None:
    resolver_dir = Path("/etc/netns") / NAMESPACE
    if (
        NAMESPACE in run("ip", "netns", "list")
        or Path("/sys/class/net/" + INTERFACE).exists()
        or resolver_dir.exists()
    ):
        raise RuntimeError("Verification namespace or interface already exists")


def _translated_endpoints(profile: str) -> str:
    configuration = run("wg-quick", "strip", profile).replace(
        "Endpoint = socrat.alchemmist.xyz:51830", "Endpoint = 127.0.0.1:51830"
    )
    return configuration.replace(
        "Endpoint = socrat.alchemmist.xyz:51831", "Endpoint = 192.168.0.24:51830"
    )


def _verify_ssh_banners(expected_keys: dict[str, str]) -> None:
    for address in ADDRESSES:
        code = (
            'import socket; s=socket.create_connection(("'
            + address
            + '",2222),8); print(s.recv(128).decode().strip()); s.close()'
        )
        banner = net("python3", "-c", code)
        if not banner.startswith("SSH-2.0-"):
            raise RuntimeError("Unexpected SSH banner from " + address)
        scanned = net("ssh-keyscan", "-T", "5", "-p", "2222", "-t", "ed25519", address)
        keys = [
            " ".join(line.split()[1:3])
            for line in scanned.splitlines()
            if line and not line.startswith("#")
        ]
        if keys != [expected_keys[address]]:
            raise RuntimeError("Wrong SSH server identity at " + address)
        print(address, "correct SSH host accessible over client tunnel", flush=True)


def _verify_dns_resolvers() -> None:
    for resolver in ADDRESSES[:3]:
        for name, expected in [
            ("0.socrat.alchemmist.xyz", "10.250.0.1"),
            ("1.socrat.alchemmist.xyz", "10.250.0.3"),
            ("2.socrat.alchemmist.xyz", "10.250.0.2"),
            ("3.socrat.alchemmist.xyz", "10.250.0.5"),
        ]:
            answer = net("dig", "@" + resolver, name, "A", "+short", "+time=3", "+tries=1").strip()
            if answer != expected:
                raise RuntimeError("Incorrect private DNS answer for " + name)
        for transport in ([], ["+tcp"]):
            answer = net(
                "dig",
                "@" + resolver,
                "debian.org",
                "A",
                "+short",
                "+time=3",
                "+tries=1",
                *transport,
            ).strip()
            if not answer or answer.startswith(";"):
                raise RuntimeError("Public DNS failed on " + resolver)
        print(resolver, "private DNS and public UDP/TCP DNS passed", flush=True)


def _verify_blocked_recovery_port() -> None:
    code = 'import socket; s=socket.socket(); s.settimeout(3); result=s.connect_ex(("10.250.0.5",22)); s.close(); print(result); raise SystemExit(result == 0)'
    run(
        "python3",
        "-c",
        'import socket; s=socket.create_connection(("10.250.0.5",22),5); s.close()',
    )
    net("python3", "-c", code)
    print("Unrequested forwarded recovery SSH port remains blocked", flush=True)


def _cleanup(
    resolver_dir: Path,
    *,
    moved: bool,
    created_interface: bool,
    created_namespace: bool,
    created_resolver: bool,
) -> None:
    if moved:
        run("ip", "-n", NAMESPACE, "link", "delete", INTERFACE)
    elif created_interface:
        run("ip", "link", "delete", INTERFACE)
    if created_namespace:
        run("ip", "netns", "delete", NAMESPACE)
    if created_resolver:
        (resolver_dir / "resolv.conf").unlink(missing_ok=True)
        resolver_dir.rmdir()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile")
    parser.add_argument("hostkeys")
    options = parser.parse_args()
    expected_keys: dict[str, str] = json.loads(Path(options.hostkeys).read_text())
    resolver_dir = Path("/etc/netns") / NAMESPACE
    _require_clean_namespace()
    configuration = _translated_endpoints(options.profile)
    created_resolver = False
    created_namespace = False
    created_interface = False
    moved = False
    try:
        resolver_dir.mkdir(parents=True, mode=0o700)
        created_resolver = True
        (resolver_dir / "resolv.conf").write_text(
            "nameserver 10.250.0.2\nnameserver 10.250.0.1\nnameserver 10.250.0.3\n"
        )
        run("ip", "netns", "add", NAMESPACE)
        created_namespace = True
        run("ip", "link", "add", INTERFACE, "type", "wireguard")
        created_interface = True
        run("wg", "setconf", INTERFACE, "/dev/stdin", input=configuration)
        run("ip", "link", "set", INTERFACE, "netns", NAMESPACE)
        moved = True
        run("ip", "-n", NAMESPACE, "address", "add", "10.250.0.7/32", "dev", INTERFACE)
        run("ip", "-n", NAMESPACE, "link", "set", INTERFACE, "up")
        run("ip", "-n", NAMESPACE, "link", "set", "lo", "up")
        for address in ADDRESSES:
            run("ip", "-n", NAMESPACE, "route", "add", address + "/32", "dev", INTERFACE)
        time.sleep(3)
        _verify_ssh_banners(expected_keys)
        _verify_dns_resolvers()
        _verify_blocked_recovery_port()
    finally:
        _cleanup(
            resolver_dir,
            moved=moved,
            created_interface=created_interface,
            created_namespace=created_namespace,
            created_resolver=created_resolver,
        )


if __name__ == "__main__":
    main()
