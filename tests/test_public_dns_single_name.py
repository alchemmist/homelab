import hashlib
import runpy

import pytest
import yaml

from ci.quality import public_dns_single_name as audit


def test_legacy_digest_accepts_one_owner_only():
    cat = yaml.safe_load(audit.CATALOG.read_text())
    serial = 42
    render = runpy.run_path(str(audit.ROOT / "ansible/scripts/public_dns_zone.py"))[
        "render"
    ]
    old = render(serial, True, True, monori_health=(True, False))
    digest = hashlib.sha256(old.encode()).hexdigest()
    res = audit.rehearse(cat, "moscow", serial, digest)
    assert res["candidate"] == [cat["replicas"]["moscow"]["publicIP"]] and set(
        res["previous"]
    ) == {cat["replicas"][s]["publicIP"] for s in ("home", "nl")}
    for n, d in [(serial, "0" * 64), (serial + 1, digest), (0, digest)]:
        with pytest.raises(ValueError):
            audit.rehearse(cat, "moscow", n, d)
    cat["hosts"]["blog"][audit.HOST]["dns"] = "external"
    with pytest.raises(ValueError):
        audit.rehearse(cat, "home", serial, digest)


def test_reject_unrelated_or_duplicate_records():
    old = "www IN A 192.0.2.1\n@ IN MX 10 mail\n"
    new = old.replace("192.0.2.1", "192.0.2.2")
    for drift in (
        new + "@ IN MX 10 mail\n",
        new.replace("MX", "NS"),
        new + "www IN A 192.0.2.2\n",
        new.replace("www IN A", "other IN A"),
    ):
        with pytest.raises(ValueError):
            audit.delta(old, drift, "192.0.2.2", 1)


def test_preserve_order_and_do_not_infer_unique_health_from_identical_bytes():
    cat = yaml.safe_load(audit.CATALOG.read_text())
    render = runpy.run_path(str(audit.ROOT / "ansible/scripts/public_dns_zone.py"))[
        "render"
    ]
    legacy = render(42, True, True, monori_health=(False, False))
    assert legacy == render(42, True, True, monori_health=(True, True))
    digest = hashlib.sha256(legacy.encode()).hexdigest()
    assert audit.rehearse(cat, "home", 42, digest)["compatibleInputStates"] >= 2
    with pytest.raises(ValueError):
        audit.delta(
            "www IN A 192.0.2.1\n$TTL 60\n@ IN MX 10 mail\n",
            "www IN A 192.0.2.2\n@ IN MX 10 mail\n$TTL 60\n",
            "192.0.2.2",
            42,
        )


def test_dns_rehearsal_rejects_changed_owner_before_matching_known_bytes(monkeypatch):
    cat = yaml.safe_load(audit.CATALOG.read_text())
    docs = audit.owner_render(owner="blog")
    ing = next(d for d in docs if d["kind"] == "Ingress")
    ing["spec"]["rules"][1]["http"]["paths"][0]["path"] = "/posts"
    monkeypatch.setattr(audit, "owner_render", lambda *, owner: docs)
    render = runpy.run_path(str(audit.ROOT / "ansible/scripts/public_dns_zone.py"))[
        "render"
    ]
    digest = hashlib.sha256(render(42, True, True).encode()).hexdigest()
    with pytest.raises(ValueError, match="blog release"):
        audit.rehearse(cat, "home", 42, digest)
