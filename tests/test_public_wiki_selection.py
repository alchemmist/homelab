"""The public wiki owner selects one hostname without opting private releases in."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_wiki_owner_label_only_on_public_exact_host():
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/wiki-runtime.yaml").read_text())[
        "spec"
    ]
    src = app["source"]
    chart = ROOT / src["path"]
    release = src["helm"]
    args = ["helm", "template", release["releaseName"], str(chart), "-n", app["destination"]["namespace"]]
    for file in release["valueFiles"]:
        args.extend(["-f", str(chart / file)])

    def render(*opts):
        return [
            obj
            for obj in yaml.safe_load_all(
                subprocess.check_output(args + list(opts), text=True)
            )
            if obj
        ]

    def ingress(docs):
        (item,) = [d for d in docs if d["kind"] == "Ingress"]
        return item

    assert not any(d["kind"] == "Ingress" for d in render("--set", "ingress.enabled=false"))
    for flag, value in [("--set-string", "*.invalid"), ("--set", "true")]:
        invalid = subprocess.run(args + [flag, "publicWebHost=" + value], capture_output=True)
        assert invalid.returncode and b"publicWebHost" in invalid.stderr
    key = "homelab.alchemmist.xyz/public-web"
    current = render()
    item = ingress(current)
    assert item["spec"]["rules"][0]["host"] == "wiki.socrat.alchemmist.xyz"
    assert item["metadata"].pop("labels") == {key: "true"}
    assert current == render("--set-string", "publicWebHost=")
    for option in ["visibility=private", "ingress.host=other.invalid"]:
        assert key not in ingress(render("--set-string", option))["metadata"].get(
            "labels", {}
        )
