"""Check private self-IP DNS using dig inside an existing, explicitly approved probe Pod."""

import argparse
import ipaddress
import json
import re
import subprocess

import yaml

from ci.quality.public_web import CATALOG

NAMESPACE = "public-dns-rehearsal"


def check_reply(output: str, names: list[str], address: str) -> None:
    """Check the question, authoritative status and complete answer of every response."""
    blocks = output.split(";; ->>HEADER<<- ")[1:]
    if len(blocks) != len(names):
        raise ValueError("incomplete dig batch")
    for name, block in zip(names, blocks, strict=True):
        flags = re.search(r"^;; flags: ([^;]*);", block, re.MULTILINE)
        if (
            "status: NOERROR," not in block.splitlines()[0]
            or not flags
            or not {"qr", "aa"} <= set(flags[1].split())
            or {"tc", "ra"}.intersection(flags[1].split())
        ):
            raise ValueError(f"{name}: not a complete authoritative response")
        _, qmark, rest = block.partition(";; QUESTION SECTION:")
        qtext, amark, atext = rest.partition(";; ANSWER SECTION:")
        if not qmark or not amark:
            raise ValueError(f"{name}: missing question or answer section")
        question = [
            line[1:].split()
            for line in qtext.splitlines()
            if line.startswith(";") and not line.startswith(";;")
        ]
        answers = [
            line.split() for line in atext.splitlines() if line.strip() and not line.startswith(";")
        ]
        if question != [[name + ".", "IN", "A"]] or len(answers) != 1:
            raise ValueError(f"{name}: unexpected question or answer count")
        answer = answers[0]
        if (
            len(answer) != 5
            or answer[0] != name + "."
            or not answer[1].isdigit()
            or answer[2:] != ["IN", "A", address]
        ):
            raise ValueError(f"{name}: answer does not equal the replica address")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pod", help="existing tokenless DNS probe Pod in the private rehearsal namespace"
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", args.pod):
        parser.error("invalid Pod name")
    catalog = yaml.safe_load(CATALOG.read_text())
    names = sorted(
        {
            host
            for hosts in catalog["hosts"].values()
            for host, policy in hosts.items()
            if policy.get("route", "web") == "web" and policy["dns"] == "managed"
        }
    )
    if not names:
        raise ValueError("empty managed host catalog")
    kube = ["kubectl", "--namespace", NAMESPACE]
    for label, entry in catalog["replicas"].items():
        svc = json.loads(
            subprocess.check_output(
                [*kube, "get", "service", f"authority-{label}-probe", "-o", "json"], timeout=15
            )
        )["spec"]
        ip = ipaddress.ip_address(svc["clusterIP"])
        if svc["type"] != "ClusterIP" or ip not in ipaddress.ip_network("10.43.0.0/16"):
            raise ValueError(f"{label}: not a private rehearsal Service")
        for transport in ("udp", "tcp"):
            cmd = [
                *kube,
                "exec",
                "-i",
                args.pod,
                "--",
                "dig",
                "@" + str(ip),
                "+tcp" if transport == "tcp" else "+notcp",
                "+ignore",
                "+tries=1",
                "+time=2",
                "+noedns",
                "+norecurse",
                "+noall",
                "+nocmd",
                "+comments",
                "+question",
                "+answer",
                "-f",
                "/dev/stdin",
            ]
            result = subprocess.run(
                cmd,
                input="".join(f"{name}. A\n" for name in names),
                text=True,
                capture_output=True,
                timeout=30,
                check=True,
            )
            check_reply(result.stdout, names, str(ipaddress.IPv4Address(entry["publicIP"])))
            print(f"{label} {transport}: {len(names)} authoritative self-IP answers")


if __name__ == "__main__":
    main()
