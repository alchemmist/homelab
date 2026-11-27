"""Exact wire-view controls for the public authority observation (no DNS in CI)."""

import re

import pytest
import yaml

from ci.quality import public_dns_snapshot as snap
from ci.quality.public_web import CATALOG

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


def test_address_and_nodata() -> None:
    assert snap.addresses(A, HOST, "A") == ["192.0.2.1"]
    assert snap.addresses(EMPTY, HOST, "AAAA") == []
    multi = A.replace("ANSWER: 1", "ANSWER: 2") + "www.alchemmist.xyz. 60 IN A 192.0.2.2\n"
    assert snap.addresses(multi, HOST, "A") == ["192.0.2.1", "192.0.2.2"]


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        pytest.param(A + A, "no complete NOERROR reply", id="two-headers"),
        pytest.param(A.replace("qr aa", "qr"), "not strictly authoritative", id="no-aa"),
        pytest.param(A.replace("qr aa", "qr aa tc"), "not strictly authoritative", id="tc"),
        pytest.param(A.replace("qr aa", "qr aa ra"), "not strictly authoritative", id="ra"),
        pytest.param(A.replace("NOERROR", "NXDOMAIN"), "no complete NOERROR reply", id="nxdomain"),
        pytest.param(
            A.replace("ANSWER: 1", "ANSWER: 0"), "answer count mismatch", id="empty-with-section"
        ),
        pytest.param(
            A.replace("ANSWER SECTION", "AUTHORITY SECTION"),
            "missing answer section",
            id="authority-section",
        ),
        pytest.param(A.replace(";www.", ";other."), "question mismatch", id="other-question"),
        pytest.param(
            A.replace(" IN A 192.0.2.1", " IN CNAME other.example."),
            "non-address or indirect answer",
            id="cname",
        ),
        pytest.param(
            EMPTY + "www.alchemmist.xyz. 60 IN AAAA ::1",
            "question mismatch",
            id="nodata-with-row",
        ),
    ],
)
def test_reject_incomplete_or_wrong_rrset(bad: str, reason: str) -> None:
    with pytest.raises(ValueError, match=re.escape(reason)):
        snap.addresses(bad, HOST, "A")


def test_exact_managed_names() -> None:
    cat = yaml.safe_load(CATALOG.read_text())
    names = snap.questions(cat)
    assert len(names) == len(set(names))
    assert "inform.sch1357.ru" not in names
    assert "vpn.alchemmist.xyz" not in names
    assert HOST in names
    cat["hosts"]["schoolbot"]["inform.sch1357.ru"]["dns"] = "managed"
    with pytest.raises(ValueError, match=r"unexpected managed DNS name$"):
        snap.questions(cat)


@pytest.mark.parametrize(
    ("mode", "expected"), [("self", 0), ("dual", 1), ("incomplete", 1), ("ipv6", 1)]
)
def test_cli_only_accepts_full_self_ip_observation(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected: int
) -> None:
    def observe(
        site: str, ip: str, names: list[str]
    ) -> tuple[str, dict[str, dict[str, list[str] | None]]]:
        rows: dict[str, dict[str, list[str] | None]] = {
            h + "/" + t: {"A": [ip], "AAAA": []} for h in names for t in ("udp", "tcp")
        }
        if site == "nl" and mode != "self":
            drift: dict[str, dict[str, list[str] | None]] = {
                "dual": {"A": [ip, "192.0.2.1"], "AAAA": []},
                "incomplete": {"A": [ip], "AAAA": None},
                "ipv6": {"A": [ip], "AAAA": ["::1"]},
            }
            rows[HOST + "/tcp"] = drift[mode]
        return site, rows

    monkeypatch.setattr(snap, "observe", observe)
    assert snap.main() == expected
