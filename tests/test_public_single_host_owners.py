"""A release opts in one existing ordinary route, never its replacement hostname."""

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LABEL = "homelab.alchemmist.xyz/public-web"


@pytest.mark.parametrize(
    ("app", "field", "replacement"),
    [
        ("schoolbot", "ingress.host", "bot.sch1357.ru"),
        ("monori", "host", "private.invalid"),
    ],
)
def test_owner_opt_in_changes_only_one_ingress_label(app, field, replacement):
    def render(*options, release=True):
        args = ["helm", "template", app, str(ROOT / "charts" / app), "-n", app]
        if release:
            args += ["-f", str(ROOT / "deploy" / app / "values.yaml")]
        return list(
            yaml.safe_load_all(subprocess.check_output([*args, *options], text=True))
        )

    def ingress(docs):
        (row,) = [r for r in docs if r and r["kind"] == "Ingress"]
        return row

    active = render()
    owner = ingress(active)
    (host,) = [r["host"] for r in owner["spec"]["rules"]]
    catalog = yaml.safe_load((ROOT / "deploy/public-web/entrances.yaml").read_text())[
        "hosts"
    ][app]
    assert catalog[host].get("route", "web") == "web"
    assert owner["spec"]["tls"][0]["hosts"] == [host]
    assert owner["metadata"].pop("labels") == {LABEL: "true"}
    assert active == render("--set-string", "publicWebHost=")
    for docs in [
        render("--set-string", f"{field}={replacement}"),
        render(release=False),
    ]:
        assert LABEL not in ingress(docs)["metadata"].get("labels", {})
