import copy
import html
import json
import random
import secrets
import shlex
from collections.abc import Sequence
from typing import TypedDict, cast


class _Fixture(TypedDict):
    source: str
    contract: str
    visible: list[tuple[object, ...]]


FIXTURES: dict[str, _Fixture] = {
    "median": {
        "source": "exports.solve = values => { const a=values.sort(); return a[Math.floor(a.length/2)]; };\n",
        "contract": "Return the numeric median of an array: numerically sort a copy, use the middle value for odd lengths, average both middle values for even lengths, throw RangeError for empty input. Never mutate caller input.",
        "visible": [([1, 2, 3],)],
    },
    "clamp": {
        "source": "exports.solve = (value, low, high) => Math.max(low || value, Math.min(high || value, value));\n",
        "contract": "Clamp a finite number value into inclusive finite numeric bounds low and high. Zero bounds are valid. Throw RangeError when low exceeds high. Never mutate caller input.",
        "visible": [(5, 1, 10)],
    },
    "escape_html": {
        "source": """exports.solve = text => text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/&/g, '&amp;');\n""",
        "contract": "Escape raw text for HTML: replace & with &amp;, < with &lt;, > with &gt;, double quote with &quot;, and single quote with &#39;. Escape exactly once per input character, including ampersands already part of text such as &lt;. Preserve all other characters and do not mutate input.",
        "visible": [("hello",)],
    },
}


def expected(task: str, args: Sequence[object]) -> dict[str, object]:
    value: object
    if task == "median":
        values = sorted(cast("Sequence[int]", args[0]))
        if not values:
            return {"error": "RangeError"}
        n = len(values)
        value = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
    elif task == "clamp":
        value, low, high = cast("Sequence[int]", args)
        if low > high:
            return {"error": "RangeError"}
        value = max(low, min(high, value))
    else:
        value = html.escape(cast("str", args[0]), quote=True).replace("&#x27;", "&#39;")
    return {"value": value}


def fixture_files(task: str) -> dict[str, str]:
    definition = FIXTURES[task]
    tests = "const a=require('node:assert/strict');const {solve}=require('./lib.cjs');\n"
    for args in definition["visible"]:
        tests += (
            "a.deepEqual(solve(..."
            + json.dumps(args)
            + "),"
            + json.dumps(expected(task, args)["value"])
            + ");\n"
        )
    tests += "console.log('visible tests passed');\n"
    return {"lib.cjs": definition["source"], "test.cjs": tests}


def task_prompt(task: str) -> str:
    return (
        "Find and fix bugs in lib.cjs, exported function solve. Contract: "
        + FIXTURES[task]["contract"]
        + " Work at /workspace. Edit only lib.cjs; never change test.cjs or leave extra files. "
        "Do not add comments. Node and bash are installed. No installations, network, git, credentials, host access or user input. "
        "Inspect actual files, execute a failing reproduction, implement a minimal fix, run actual tests. "
        "Do not invent files or test results. Use inline node -e for extra tests. "
        "When complete use your agent completion mechanism; for mini-SWE-agent execute "
        "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT as a standalone command."
    )


def cases_for(task: str, seed: int) -> list[list[object]]:
    rng = random.Random(seed)
    if task == "median":
        cases: list[list[object]] = [[[]], [[1]], [[10, 2, 1]], [[1, 2]], [[-1, -4, -2, -3]]]
        cases += [
            [[rng.randint(-1000, 1000) for _ in range(rng.randint(1, 16))]] for _ in range(60)
        ]
    elif task == "clamp":
        cases = [[-1, 0, 3], [5, -3, 0], [1, 2, -2], [0, 0, 0]]
        cases += [
            [rng.randint(-100, 100), rng.randint(-100, 100), rng.randint(-100, 100)]
            for _ in range(60)
        ]
    else:
        cases = [[""], ['<a title="x">&\'</a>'], ["&lt;"], ["plain text"], ["<&>"]]
        alphabet = "abc xyz<&>'\"é\n"
        cases += [
            ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 60)))] for _ in range(60)
        ]
    return copy.deepcopy(cases)


VERIFIER_SCRIPT = r"""const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('./lib.cjs', 'utf8');
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
if (!Array.isArray(cases)) throw new Error('invalid cases');
const context = vm.createContext(Object.create(null), {
  codeGeneration: {strings: false, wasm: false}, microtaskMode: 'afterEvaluate'
});
const bootstrap = `(() => {
  const parse = JSON.parse;
  const stringify = JSON.stringify;
  const apply = Reflect.apply;
  const get = Reflect.get;
  const set = Reflect.set;
  const define = Reflect.defineProperty;
  const remove = Reflect.deleteProperty;
  const setProto = Reflect.setPrototypeOf;
  const prevent = Reflect.preventExtensions;
  const create = Object.create;
  const isArray = Array.isArray;
  const finite = Number.isFinite;
  const ProxyType = Proxy;
  const MapType = WeakMap;
  const mapGet = WeakMap.prototype.get;
  const mapSet = WeakMap.prototype.set;
  const moduleRecord = {exports: create(null)};
  Object.defineProperty(globalThis, 'module', {value: moduleRecord});
  Object.defineProperty(globalThis, 'exports', {value: moduleRecord.exports});
  Object.defineProperty(globalThis, '__trustedRun', {value: function (encoded) {
    let mutated = false;
    const cache = new MapType();
    function wrap(value) {
      if (value === null || typeof value !== 'object') return value;
      const old = apply(mapGet, cache, [value]);
      if (old) return old;
      const proxy = new ProxyType(value, {
        get(target, key, receiver) {return wrap(get(target, key, receiver));},
        set(target, key, item) {mutated = true; return set(target, key, item);},
        deleteProperty(target, key) {mutated = true; return remove(target, key);},
        defineProperty(target, key, item) {mutated = true; return define(target, key, item);},
        setPrototypeOf(target, item) {mutated = true; return setProto(target, item);},
        preventExtensions(target) {mutated = true; return prevent(target);}
      });
      apply(mapSet, cache, [value, proxy]);
      return proxy;
    }
    const record = create(null);
    try {
      const args = parse(encoded);
      if (!isArray(args)) throw new TypeError('invalid args');
      const value = apply(moduleRecord.exports.solve, undefined, wrap(args));
      const kind = typeof value;
      if (kind === 'string' || kind === 'boolean' || value === null || (kind === 'number' && finite(value))) {
        record.value = value;
      } else {
        record.invalid = 'nonprimitive result';
      }
    } catch (error) {
      let name = 'Error';
      try {
        const value = error && error.name;
        if (typeof value === 'string' && value.length <= 64) name = value;
      } catch (ignored) {}
      record.error = name;
    }
    record.mutated = mutated;
    return stringify(record);
  }});
  for (const target of [Object.prototype, Array.prototype, Function.prototype,
                        WeakMap.prototype, JSON, Reflect]) Object.freeze(target);
})()`;
vm.runInContext(bootstrap, context, {timeout: 1000});
vm.runInContext(source, context, {filename: 'lib.cjs', timeout: 1000});
const results = [];
for (const args of cases) {
  const invocation = '__trustedRun(' + JSON.stringify(JSON.stringify(args)) + ')';
  try {
    const encoded = vm.runInContext(invocation, context, {timeout: 100});
    if (typeof encoded !== 'string') throw new Error('nonprimitive boundary');
    results.push(JSON.parse(encoded));
  } catch (ignored) {
    results.push({error: 'VerifierExecutionError', mutated: true});
  }
}
process.stdout.write(JSON.stringify({results}));
"""


def verifier_command(task: str, seed: int) -> tuple[str, str, list[list[object]]]:
    cases = cases_for(task, seed)
    nonce = secrets.token_hex(16)
    return "node -e " + shlex.quote(VERIFIER_SCRIPT), nonce, cases


def seal_execution(nonce: str, result: object) -> object:
    if not isinstance(result, dict):
        return result
    sealed = dict(result)
    output = result.get("output")
    if not isinstance(output, (str, bytes)):
        return sealed
    try:
        data = json.loads(output)
    except (ValueError, TypeError):
        return sealed
    if not isinstance(data, dict) or "nonce" in data or not isinstance(data.get("results"), list):
        sealed["output"] = ""
        return sealed
    sealed["output"] = json.dumps({"nonce": nonce, "results": data["results"]})
    return sealed


def check_verdict(
    task: str,
    nonce: str,
    cases: list[list[object]],
    result: object,
) -> dict[str, object]:
    if not isinstance(result, dict):
        return {"accepted": False, "reason": "missing or invalid verifier output"}
    code = result.get("returncode")
    if type(code) is not int or code != 0:
        return {"accepted": False, "reason": "verifier process failed", "exit_code": code}
    output = result.get("output")
    if not isinstance(output, (str, bytes)):
        return {"accepted": False, "reason": "missing or invalid verifier output"}
    try:
        data = json.loads(output)
    except (ValueError, TypeError):
        return {"accepted": False, "reason": "missing or invalid verifier output"}
    if (
        not isinstance(data, dict)
        or data.get("nonce") != nonce
        or not isinstance(data.get("results"), list)
        or len(data["results"]) != len(cases)
    ):
        return {"accepted": False, "reason": "incomplete verifier output"}
    for index, (args, actual) in enumerate(zip(cases, data["results"])):
        want = expected(task, args) | {"mutated": False}
        if (
            not isinstance(actual, dict)
            or actual.get("mutated") is not False
            or isinstance(actual.get("value"), bool)
            or actual != want
        ):
            return {
                "accepted": False,
                "reason": "contract mismatch",
                "case": index,
                "arguments": args,
                "expected": want,
                "actual": actual,
            }
    return {"accepted": True, "cases": len(cases)}
