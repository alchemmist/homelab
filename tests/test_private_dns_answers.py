"""Exercise rejection of plausible but insufficient private DNS proof."""

import re
import sys

import pytest

from ci.quality import private_dns_answers as audit
from ci.quality.private_dns_answers import check_reply

REPLY = """;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 15
;; flags: qr aa; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 0
;; QUESTION SECTION:
;example.test. IN A

;; ANSWER SECTION:
example.test. 60 IN A 192.0.2.1
"""


def test_batch() -> None:
    check_reply(
        REPLY + REPLY.replace("example.test.", "two.test."),
        ["example.test", "two.test"],
        "192.0.2.1",
    )


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        pytest.param("", "incomplete dig batch", id="empty"),
        pytest.param(
            REPLY.replace("qr aa", "qr"),
            "example.test: not a complete authoritative response",
            id="no-aa",
        ),
        pytest.param(
            REPLY.replace("qr aa", "qr aa tc"),
            "example.test: not a complete authoritative response",
            id="tc",
        ),
        pytest.param(
            REPLY.replace("NOERROR", "SERVFAIL"),
            "example.test: not a complete authoritative response",
            id="servfail",
        ),
        pytest.param(
            REPLY.replace(";example.test.", ";other.test."),
            "example.test: unexpected question or answer count",
            id="other-question",
        ),
        pytest.param(
            REPLY.replace("192.0.2.1", "192.0.2.2"),
            "example.test: answer does not equal the replica address",
            id="wrong-ip",
        ),
        pytest.param(
            REPLY + "example.test. 60 IN A 192.0.2.2\n",
            "example.test: unexpected question or answer count",
            id="extra-row",
        ),
    ],
)
def test_not_acceptance(result: str, reason: str) -> None:
    with pytest.raises(ValueError, match=re.escape(reason)):
        check_reply(result, ["example.test"], "192.0.2.1")


@pytest.mark.parametrize("failed", [None, ("home", "udp"), ("nl", "tcp")])
def test_all_sites_attempted_without_partial_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed: tuple[str, str] | None,
) -> None:
    seen: list[tuple[str, str]] = []

    def run(
        pod: str,
        label: str,
        _entry: dict[str, object],
        names: list[str],
        transport: str,
    ) -> None:
        """Stand in for check_case and record each attempted site/transport pair."""
        assert pod == "fixture"
        assert "inform.sch1357.ru" not in names
        assert "venice.socrat.alchemmist.xyz" in names
        seen.append((label, transport))
        if seen[-1] == failed:
            message = "invalid batch"
            raise ValueError(message)

    expected = [(label, t) for label in ("home", "nl", "moscow") for t in ("udp", "tcp")]
    assert audit.KUBE == [
        "kubectl",
        "--context=Socrat",
        "--namespace",
        "public-dns-rehearsal",
    ]
    monkeypatch.setattr(audit, "check_case", run)
    monkeypatch.setattr(sys, "argv", ["probe", "fixture"])
    assert audit.main() == int(failed is not None)
    assert len(seen) == len(expected)
    assert set(seen) == set(expected)
    assert capsys.readouterr().out.count("not verified") == int(failed is not None)
