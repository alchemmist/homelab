#!/usr/bin/env python3
"""One route-aggregated TV timeline; preserve owner deletions/layout and Argo bottom boundary."""
import copy
import json
import runpy
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "charts/monitoring-k3s/dashboards/traffic-light.json"
IDS = {937, 938}


def build(source=None):
    d = copy.deepcopy(source if source is not None else json.loads(SOURCE.read_text()))
    owner = {p["id"]: p for p in d["panels"]}
    bottom = owner[909]["gridPos"]["y"] + owner[909]["gridPos"]["h"]
    panel = owner[938]
    panel["title"] = ""
    panel.pop("description", None)
    target = panel["targets"][0]
    target.update(expr=('sum by (requested_model) (label_replace(increase(litellm_requests_metric_total{'
                        'job="litellm",requested_model!="",requested_model!="None",'
                        'api_key_alias!~"venice-acceptance-.*"}[1m]), '
                        '"requested_model", "v-deepseek-uc", "requested_model", "^venice-deepseek$"))'),
                  legendFormat="{{requested_model}}")
    panel["fieldConfig"]["defaults"]["color"] = {"mode": "palette-classic-by-name"}
    colors = {"qwen3.8-27b": "#73BF69", "v-deepseek-uc": "#5794F2", "o-deepseek": "#FF9830"}
    panel["fieldConfig"]["overrides"] = [
        {"matcher": {"id": "byName", "options": name}, "properties": [
            {"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]} for name, color in colors.items()]
    panel["options"]["legend"]["showLegend"] = False
    d["panels"] = [p for p in d["panels"] if p["id"] != 937]
    occupied = set()
    for p in d["panels"]:
        g = p["gridPos"]
        cells = {(x,y) for x in range(g["x"],g["x"]+g["w"]) for y in range(g["y"],g["y"]+g["h"])}
        if cells & occupied or not(0 <= g["x"] < g["x"]+g["w"] <= 24 and 0 <= g["y"] < g["y"]+g["h"] <= bottom):
            raise ValueError("Overlap or Argo bottom boundary exceeded; preserve owner layout and stop")
        occupied |= cells
    return d


def write(d):
    # Preserve existing owned-widget compaction and actual ConfigMap size budget.
    quality = runpy.run_path(str(SOURCE.parents[3] / "scripts/build-traffic-light-quality.py"))
    quality["write"](d)
    text = SOURCE.read_text()
    for p in d["panels"]:
        if p["id"] not in IDS | {21, 22, 23, 909, 939}:
            continue
        block = "\n".join("    "+line for line in json.dumps(p,ensure_ascii=False,indent=2).splitlines())
        assert text.count(block) == 1
        text = text.replace(block,"    "+json.dumps(p,ensure_ascii=False,separators=(",",":")),1)
    SOURCE.write_text(text)


if __name__ == "__main__":
    write(build())
