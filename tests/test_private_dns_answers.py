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
