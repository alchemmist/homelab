"""Exact wire-view controls for the public authority observation (no DNS in CI)."""

import pytest
import yaml

from ci.quality import public_dns_snapshot as snap

HOST = "www.alchemmist.xyz"
A = """;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 12
;; flags: qr aa; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 0
;; QUESTION SECTION:
;www.alchemmist.xyz. IN A
;; ANSWER SECTION:
www.alchemmist.xyz. 60 IN A 192.0.2.1
"""
EMPTY = (
    A.replace("ANSWER: 1", "ANSWER: 0")
    .split(";; ANSWER SECTION:")[0]
    .replace(" IN A\n", " IN AAAA\n")
)


def test_address_and_nodata():
    assert (
        snap.addresses(A, HOST, "A") == ["192.0.2.1"]
        and snap.addresses(EMPTY, HOST, "AAAA") == []
    )
    multi = (
        A.replace("ANSWER: 1", "ANSWER: 2") + "www.alchemmist.xyz. 60 IN A 192.0.2.2\n"
    )
    assert snap.addresses(multi, HOST, "A") == ["192.0.2.1", "192.0.2.2"]


@pytest.mark.parametrize(
    "bad",
    [
        A + A,
        A.replace("qr aa", "qr"),
        A.replace("qr aa", "qr aa tc"),
        A.replace("qr aa", "qr aa ra"),
        A.replace("NOERROR", "NXDOMAIN"),
        A.replace("ANSWER: 1", "ANSWER: 0"),
        A.replace("ANSWER SECTION", "AUTHORITY SECTION"),
        A.replace(";www.", ";other."),
        A.replace(" IN A 192.0.2.1", " IN CNAME other.example."),
        EMPTY + "www.alchemmist.xyz. 60 IN AAAA ::1",
    ],
)
def test_reject_incomplete_or_wrong_rrset(bad):
    with pytest.raises(ValueError):
        snap.addresses(bad, HOST, "A")


def test_exact_managed_names():
    cat = yaml.safe_load(snap.CATALOG.read_text())
    names = snap.questions(cat)
    assert (
        len(names) == len(set(names))
        and "inform.sch1357.ru" not in names
        and "vpn.alchemmist.xyz" not in names
        and HOST in names
    )
    cat["hosts"]["schoolbot"]["inform.sch1357.ru"]["dns"] = "managed"
    with pytest.raises(ValueError):
        snap.questions(cat)


@pytest.mark.parametrize(
    "mode,expected", [("self", 0), ("dual", 1), ("incomplete", 1), ("ipv6", 1)]
)
def test_cli_only_accepts_full_self_ip_observation(monkeypatch, mode, expected):
    def observe(site, ip, names):
        rows = {
            h + "/" + t: {"A": [ip], "AAAA": []} for h in names for t in ("udp", "tcp")
        }
        if site == "nl" and mode != "self":
            rows[HOST + "/tcp"] = {
                "dual": {"A": [ip, "192.0.2.1"], "AAAA": []},
                "incomplete": {"A": [ip], "AAAA": None},
                "ipv6": {"A": [ip], "AAAA": ["::1"]},
            }[mode]
        return site, rows

    monkeypatch.setattr(snap, "observe", observe)
    assert snap.main() == expected
