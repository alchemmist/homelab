"""Exercise rejection of plausible but insufficient private DNS proof."""

import pytest

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
    "result",
    [
        "",
        REPLY.replace("qr aa", "qr"),
        REPLY.replace("qr aa", "qr aa tc"),
        REPLY.replace("NOERROR", "SERVFAIL"),
        REPLY.replace(";example.test.", ";other.test."),
        REPLY.replace("192.0.2.1", "192.0.2.2"),
        REPLY + "example.test. 60 IN A 192.0.2.2\n",
    ],
)
def test_not_acceptance(result: str) -> None:
    with pytest.raises(ValueError):
        check_reply(result, ["example.test"], "192.0.2.1")


@pytest.mark.parametrize("failed", [None, ("home", "udp"), ("nl", "tcp")])
def test_all_sites_attempted_without_partial_success(monkeypatch, capsys, failed):
    import sys

    from ci.quality import private_dns_answers as audit

    seen = []

    def run(pod, label, entry, names, transport):
        assert (
            pod == "fixture"
            and "inform.sch1357.ru" not in names
            and "venice.socrat.alchemmist.xyz" in names
        )
        seen.append((label, transport))
        if seen[-1] == failed:
            raise ValueError("invalid batch")

    assert audit.KUBE == [
        "kubectl",
        "--context=Socrat",
        "--namespace",
        "public-dns-rehearsal",
    ]
    monkeypatch.setattr(audit, "check_case", run)
    monkeypatch.setattr(sys, "argv", ["probe", "fixture"])
    assert audit.main() == int(failed is not None)
    assert len(seen) == 6 and set(seen) == {
        (label, t) for label in ("home", "nl", "moscow") for t in ("udp", "tcp")
    }
    assert capsys.readouterr().out.count("not verified") == int(failed is not None)
