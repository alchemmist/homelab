"""Public exposure contract: aggregate labels only and honest activity semantics."""

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Grafana dashboard coordinates use a 24-column grid. This panel spans it.
PUBLIC_PANEL_GRID_WIDTH = 24


def test_public_llm_dashboard_is_one_safe_panel() -> None:
    """Require one aggregate panel and the fixed public rate expression."""
    d = json.loads((ROOT / "charts/monitoring-k3s/dashboards/llm-activity-public.json").read_text())
    assert d["uid"] == "socrat-llm-activity-public"
    assert len(d["panels"]) == 1
    assert d["templating"] == {"list": []}
    assert d["annotations"] == {"list": []}
    assert d["links"] == []
    assert d["refresh"] == "10s"
    p = d["panels"][0]
    assert p["gridPos"]["w"] == PUBLIC_PANEL_GRID_WIDTH
    assert p["targets"][0]["expr"] == (
        "sum by (api_key_alias) (rate(litellm_requests_metric_total"
        '{job="litellm",api_key_alias!="",api_key_alias!="None"}'
        "[$__rate_interval])) * 60"
    )
    assert p["targets"][0]["legendFormat"] == "{{api_key_alias}}"
    assert p["fieldConfig"]["defaults"]["custom"]["spanNulls"] is False
    assert "zero does not guarantee" in p["description"]
    assert "completed" in p["title"]


def _same_statement(body: list[ast.stmt], expected: str) -> ast.stmt:
    """Require exactly one complete statement, independent of quotes and spacing."""
    signature = ast.dump(ast.parse(expected).body[0], include_attributes=False)
    matches = [node for node in body if ast.dump(node, include_attributes=False) == signature]
    assert len(matches) == 1
    return matches[0]


def _sharing_contract(source: str) -> None:
    """Require all five original security contracts and refusal-before-publication."""
    module = ast.parse(source)
    mains = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert len(mains) == 1
    # A docstring is inert; only discard an actual leading function docstring.
    guards = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "need"]
    assert len(guards) == 1
    guard = guards[0]
    if ast.get_docstring(guard) is not None:
        guard.body.pop(0)
    # Ignore simple type names/literals, never executable annotation expressions.
    for arg in guard.args.args:
        assert arg.annotation is None or isinstance(arg.annotation, (ast.Name, ast.Constant))
        arg.annotation = None
    assert guard.returns is None or isinstance(guard.returns, (ast.Name, ast.Constant))
    guard.returns = None
    _same_statement(
        module.body,
        "def need(ok, msg):\n    if not ok:\n        raise RuntimeError(msg)",
    )
    locks = [n for n in mains[0].body if isinstance(n, ast.With)]
    assert len(locks) == 1
    body = locks[0].body
    locked = _same_statement(body, "fcntl.flock(lock, fcntl.LOCK_EX)")
    settings = _same_statement(body, 'code, settings = api("GET", "/api/admin/settings")')
    section = _same_statement(
        body,
        'anonymous = cast("dict[str, object]", settings.get("auth.anonymous", {}))',
    )
    anonymous = _same_statement(
        body,
        'need(code == 200 and anonymous.get("enabled") '
        'in [False, "false"], "Organization anonymous access drift; refuse publication")',
    )
    content = _same_statement(
        body,
        'need(live["panels"] == expected["panels"] '
        'and live["templating"] == {"list": []} '
        'and live["annotations"] == {"list": []} and live["links"] == [], '
        '"Unexpected public content; refuse publication")',
    )
    desired = _same_statement(
        body,
        'desired = {"isEnabled": True, "annotationsEnabled": False, '
        '"timeSelectionEnabled": True, "share": "public"}',
    )
    apply_signature = ast.dump(ast.parse("a.apply", mode="eval").body, include_attributes=False)
    applies = [
        n
        for n in body
        if isinstance(n, ast.If) and ast.dump(n.test, include_attributes=False) == apply_signature
    ]
    assert len(applies) == 1
    apply = applies[0]
    approval = _same_statement(
        apply.body,
        'need(a.approve_plan_hash == digest, "Fresh exact plan approval required")',
    )
    post = _same_statement(apply.body, 'code, after = api("POST", endpoint, desired)')
    assert apply.body[0] is approval
    assert apply.body.index(approval) < apply.body.index(post)
    assert body.index(locked) < body.index(settings)
    assert body[body.index(settings) : body.index(anonymous) + 1] == [
        settings,
        section,
        anonymous,
    ]
    assert body.index(anonymous) < body.index(content) < body.index(desired) < body.index(apply)
    writes = [
        n
        for n in ast.walk(mains[0])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "api"
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and n.args[0].value != "GET"
    ]
    assert isinstance(post, ast.Assign)
    assert writes == [post.value]


def test_public_sharing_does_not_enable_org_anonymous() -> None:
    """Preserve anonymous refusal, private annotations, selection, plan and content guards."""
    _sharing_contract((ROOT / "scripts/grafana-llm-public.py").read_text())


@pytest.mark.parametrize(
    ("needle", "replacement"),
    [
        ('[False, "false"]', '[True, "true"]'),
        ('"annotationsEnabled": False', '"annotationsEnabled": True'),
        ('"timeSelectionEnabled": True', '"timeSelectionEnabled": False'),
        ("a.approve_plan_hash == digest", "True"),
        ('live["panels"] == expected["panels"]', "True"),
        ("code == 200 and anonymous.get", "code == 200 or anonymous.get"),
        ('settings.get("auth.anonymous", {})', '{"enabled": False}'),
        ("msg: str)", 'msg: str = "")'),
        ("ok: bool,", "ok: side_effect(),"),
        ("raise RuntimeError(msg)", "return"),
    ],
)
def test_public_sharing_contract_rejects_security_mutations(needle: str, replacement: str) -> None:
    """Reject synthetic bypasses by parsing only; never import or run the publisher."""
    source = (ROOT / "scripts/grafana-llm-public.py").read_text()
    _sharing_contract(source)
    assert source.count(needle) == 1
    changed = source.replace(needle, replacement, 1)
    with pytest.raises(AssertionError):
        _sharing_contract(changed)
