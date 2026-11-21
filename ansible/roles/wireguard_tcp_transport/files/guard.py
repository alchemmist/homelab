"""Install and verify the iptables UDP rule for the WireGuard transport peer."""
import ipaddress
import re
import shutil
import subprocess
import sys


def main():
    interface, address, port = sys.argv[1:]
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", interface):
        msg = "Invalid interface"
        raise ValueError(msg)
    ipaddress.IPv4Address(address)
    if not 0 < int(port) < 65536:
        msg = "Invalid UDP port"
        raise ValueError(msg)
    binary = shutil.which("iptables")
    if not binary:
        msg = "iptables is required"
        raise RuntimeError(msg)
    rule = [
        "-i",
        interface,
        "-s",
        address,
        "-p",
        "udp",
        "--sport",
        port,
        "--dport",
        port,
        "-m",
        "comment",
        "--comment",
        "homelab-wg-tcp-direct-guard",
        "-j",
        "DROP",
    ]
    result = subprocess.run([binary, "-w", "10", "-C", "INPUT", *rule], capture_output=True)
    if result.returncode == 1:
        subprocess.run([binary, "-w", "10", "-I", "INPUT", "1", *rule], check=True)
    elif result.returncode != 0:
        msg = "Unable to inspect the WireGuard direct transport guard"
        raise RuntimeError(msg)


if __name__ == "__main__":
    main()
