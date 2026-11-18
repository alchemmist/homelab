"""Exercise only the queue predicate on synthetic data, never n8n or a model."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from scripts.quality.common import command

ROOT = Path(__file__).resolve().parents[1]
RUNNER = """
import fs from 'node:fs';
import vm from 'node:vm';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const sample = (name, value='0', instance='fixture') => ({
  metric: {__name__: 'vllm:num_requests_'+name, model_name: 'qwen3.8-27b', instance},
  value: [1700000000, value]
});
const payload = rows => ({status:'success', data:{resultType:'vector', result:rows}});
const pair = () => [sample('running'), sample('waiting')];
const cases = [
 ['idle',payload(pair()),'step'],
 ['running',payload([sample('running','1'),sample('waiting')]),'skip'],
 ['waiting',payload([sample('running'),sample('waiting','2')]),'skip'],
 ['multiple-targets',payload([...pair(),sample('running','1','other'),sample('waiting','0','other')]),'skip'],
 ['missing-payload',{},null],
 ['empty',payload([]),null],
 ['missing-running',payload([sample('waiting')]),null],
 ['missing-waiting',payload([sample('running')]),null],
 ['mismatched-target',payload([sample('running'),sample('waiting','0','other')]),null],
 ['duplicate',payload([...pair(),sample('running')]),null],
 ['unknown-name',payload([sample('other'),sample('waiting')]),null],
 ['error-status',{...payload(pair()),status:'error'},null],
 ['wrong-type',{status:'success',data:{resultType:'matrix',result:pair()}},null],
];
for (const value of ['', 'NaN','Infinity','-Infinity','1e999','-1','invalid','0x0',' 0 ']) {
 cases.push(['invalid-'+value,payload([sample('running',value),sample('waiting')]),null]);
}
const missingName = sample('running'); delete missingName.metric.__name__;
cases.push(['missing-name',payload([missingName,sample('waiting')]),null]);
const wrongModel = sample('running'); wrongModel.metric.model_name='other';
cases.push(['wrong-model',payload([wrongModel,sample('waiting')]),null]);
const badStamp = sample('running'); badStamp.value[0]=0;
cases.push(['timestamp',payload([badStamp,sample('waiting')]),null]);
const answers=[];
for (const [name,data,expected] of cases) {
 let actual, rejected=false;
 try {
  const result=vm.runInNewContext(
    '(function(){'+input.source+'\\n})()',{$json:data},{timeout:1000});
  actual=result[0].json.action;
 } catch {rejected=true;}
 const ok=expected===null ? rejected : (!rejected && actual===expected);
 if (!ok) throw new Error('Queue predicate contract failed: '+name);
 answers.push(name);
}
console.log(JSON.stringify({passed:answers}));
"""


def _mapping(value: object) -> dict[str, object]:
    """Validate each JSON key without inventing types for unknown nested fields."""
    assert isinstance(value, dict)
    result: dict[str, object] = {}
    for key, item in value.items():
        assert isinstance(key, str)
        result[key] = item
    return result


def _parameters(name: str) -> dict[str, object]:
    """Select one actual workflow node without importing any provisioning code."""
    data = _mapping(json.loads((ROOT / "docs/n8n/lms-certify/workflow.json").read_text()))
    nodes = data["nodes"]
    assert isinstance(nodes, list)
    matches = [_mapping(node) for node in nodes if _mapping(node).get("name") == name]
    assert len(matches) == 1
    return _mapping(matches[0]["parameters"])


def test_queue_selector_preserves_both_metric_names_without_or_collision() -> None:
    """A direct metric selector cannot discard waiting via vector-union label matching."""
    url = _parameters("Qwen queue")["url"]
    assert isinstance(url, str)
    assert parse_qs(urlsplit(url).query) == {
        "query": ['{__name__=~"vllm:num_requests_(running|waiting)",model_name="qwen3.8-27b"}'],
    }


def test_queue_predicate_refuses_incomplete_or_invalid_telemetry() -> None:
    """Run the actual pure JS predicate only, with no HTTP nodes/activation/inference."""
    source = _parameters("Model free?")["jsCode"]
    assert isinstance(source, str)
    result = command(
        ["node", "--input-type=module", "-e", RUNNER],
        stdin=json.dumps({"source": source}),
    )
    report = _mapping(json.loads(result.stdout))
    passed = report["passed"]
    assert isinstance(passed, list)
    expected_count = 25
    assert len(passed) == expected_count
