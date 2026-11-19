"""Exercise only the queue predicate on synthetic data, never n8n or a model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.quality.common import command

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = (
    "Admission:",
    "Generate solution:",
    "Author blind tests:",
    "Repair solution:",
    "Add missing corner cases:",
)
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
const envelope = body => ({statusCode:200,body});
const stamps = body => envelope(payload((body?.data?.result || []).map(r => ({
 metric:{...r.metric,queue_metric:r.metric?.__name__?.split('_').at(-1)},
 value:[1700000000,'1700000000']
}))));
const answers=[];
function verify(name, values, timestamps, expected) {
 const result=vm.runInNewContext('(function(){'+input.source+'\\n})()', {
  $json:timestamps, $:()=>({item:{json:values}}), Date:{now:()=>1700000000000}
 },{timeout:1000}).json;
 const ok=expected===null ? result.idle===false && result.telemetryValid===false :
   result.telemetryValid===true && result.idle===(expected==='step');
 if (!ok) throw new Error('Queue predicate contract failed: '+name);
 answers.push(name);
}
for (const [name,data,expected] of cases) verify(name,envelope(data),stamps(data),expected);
const good = payload(pair());
verify('both-targets-idle',envelope(payload([...pair(),sample('running','0','other'),sample('waiting','0','other')])),
 stamps(payload([...pair(),sample('running','0','other'),sample('waiting','0','other')])), 'step');
verify('duplicate-complete-pairs',envelope(payload([...pair(),...pair()])),stamps(payload([...pair(),...pair()])),null);
verify('http-failure',{statusCode:503,body:good},stamps(good),null);
verify('transport-error',{...envelope(good),error:'synthetic'},stamps(good),null);
verify('freshness-type',envelope(good),{statusCode:200,body:{...good,data:{...good.data,resultType:'matrix'}}},null);
for (const value of ['1699999954','1700000006','NaN','Infinity','',' 1700000000 ','1e999']) {
 const t=stamps(good);t.body.data.result[0].value[1]=value;
 verify('bad-freshness-'+value,envelope(good),t,null);
}
const duplicate=stamps(good);duplicate.body.data.result[1]=duplicate.body.data.result[0];
verify('duplicate-freshness',envelope(good),duplicate,null);
const missing=stamps(good);missing.body.data.result.pop();
verify('missing-freshness',envelope(good),missing,null);
const mismatch=stamps(good);mismatch.body.data.result[0].metric.instance='other';
verify('mismatched-freshness',envelope(good),mismatch,null);
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


@pytest.mark.parametrize("prefix", PREFIXES)
def test_queue_selector_preserves_both_metric_names_without_or_collision(prefix: str) -> None:
    """Every actual phase keeps both counters and independent original-sample stamps."""
    params = _parameters(prefix + " queue depth")
    assert (
        params["url"]
        == "http://kube-prometheus-stack-prometheus.cattle-monitoring-system.svc.cluster.local:9090/api/v1/query"
    )
    assert params["queryParameters"] == {
        "parameters": [
            {
                "name": "query",
                "value": '{__name__=~"vllm:num_requests_(running|waiting)",model_name="qwen3.8-27b"}',
            }
        ]
    }
    stamps = _parameters(prefix + " sample freshness")
    expected = " or ".join(
        "label_replace(timestamp(vllm:num_requests_"
        + metric
        + '{model_name="qwen3.8-27b"}), "queue_metric", "'
        + metric
        + '", "model_name", ".*")'
        for metric in ("running", "waiting")
    )
    assert stamps["queryParameters"] == {"parameters": [{"name": "query", "value": expected}]}
    gate = _parameters(prefix + " model idle?")
    assert "$json.idle === true" in json.dumps(gate)


@pytest.mark.parametrize("prefix", PREFIXES)
def test_queue_predicate_refuses_incomplete_or_invalid_telemetry(prefix: str) -> None:
    """Retain all25legacy cases, distinguish malformed from busy, and test freshness."""
    source = _parameters(prefix + " verify both metrics")["jsCode"]
    assert isinstance(source, str)
    result = command(
        ["node", "--input-type=module", "-e", RUNNER], stdin=json.dumps({"source": source})
    )
    report = _mapping(json.loads(result.stdout))
    passed = report["passed"]
    assert isinstance(passed, list)
    assert len(passed) == 40
