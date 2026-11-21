"""Opt-in continuation for exactly one conversation; no model or GitHub credentials."""

import json
import os
import re
import socket
import sqlite3
import time
import types
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


@dataclass
class MonitorState:
    """Mutable scheduling state for one monitored conversation."""

    bridge_was_down: bool = False
    probed: bool = False
    attempted: str | None = None
    after: float = 0.0
    parallel_failures: int = 0
    last_parallel: str | None = None


class Tracker(TypedDict):
    """Per-pass worker scheduling bookkeeping shared between helpers."""

    attempted: set[tuple[str, str]]
    failures: dict[str, int]
    delay: dict[str, float]
    now: float


class Conversation(TypedDict):
    """Identity and client for one monitored conversation."""

    cid: str
    api: types.FunctionType
    conv: dict[str, object]


def eligible(status, event):
    return (
        status == "error"
        and event.get("kind") == "ConversationErrorEvent"
        and event.get("source") == "environment"
        and event.get("code") == "MaxIterationsReached"
        and bool(event.get("id"))
    )


def retry_parallel(event):
    if event.get("kind") != "ConversationErrorEvent" or event.get("source") != "environment":
        return None
    text = event.get("detail", "")
    if (
        event.get("code", "LLMRateLimitError") != "LLMRateLimitError"
        or "RateLimitError" not in text
    ):
        return None
    if re.search(r"\bmax_parallel_requests=[1-9]\d* requests in flight\b", text):
        return 0
    if "Limit type: max_parallel_requests." not in text:
        return None
    m = re.search(r"Limit resets at: (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC", text)
    return (
        datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp() + 15
        if m
        else None
    )


def busy_resume(cid, api, events, now, allowed=lambda: True, path="/wait-state/waits.db"):
    """Persist only scheduling metadata. Never replay a tool call or user message."""
    ev = next((e for e in events if e["kind"] != "ConversationStateUpdateEvent"), {})
    reset = retry_parallel(ev)
    eid = ev.get("id")
    if reset is None or not eid:
        return False
    c = api()
    if c["execution_status"] != "error":
        return False
    model = c["agent"]["llm"]["model"]
    group = re.search(r"model group '([a-zA-Z0-9_.-]+)'", ev["detail"])
    if group:
        model = "openai/" + group[1]
    with closing(sqlite3.connect(path, timeout=8)) as db, db:
        db.execute(
            "create table if not exists waits(cid text primary key, model text, "
            "eid text, due real, n integer)"
        )
        db.execute("create table if not exists gates(model text primary key, until_ts real)")
        db.execute("begin immediate")
        row = db.execute("select eid,due,n from waits where cid=?", (cid,)).fetchone()
        if not row or row[0] != eid:
            n = min(5, row[2] + 1) if row and now - row[1] < 1800 else 0
            due = max(reset, now + min(900, 60 * 2**n))
            db.execute("insert or replace into waits values(?,?,?,?,?)", (cid, model, eid, due, n))
            return False
        gate = db.execute("select until_ts from gates where model=?", (model,)).fetchone()
        if now < row[1] or (gate and now < gate[0]):
            return False
        if not allowed() or api()["execution_status"] != "error":
            return False
        latest = api("/events/search?sort_order=TIMESTAMP_DESC&limit=12")["items"]
        if (
            next((e.get("id") for e in latest if e["kind"] != "ConversationStateUpdateEvent"), None)
            != eid
        ):
            return False
        # Commit cooldown before HTTP: lost acknowledgement cannot trigger a burst.
        db.execute("update waits set due=? where cid=?", (now + 900, cid))
        db.execute("insert or replace into gates values(?,?)", (model, now + 60))
        db.commit()
        ok = api("/run", "POST").get("success")
        print("capacity resume", cid, model, bool(ok), flush=True)
        return bool(ok)


def final_message(events, qa=False):
    # Never infer an agent finish from arbitrary user/file/tool text.
    for ev in events:
        if ev.get("kind") == "ConversationStateUpdateEvent" and ev.get("key") in (
            "execution_status",
            "stats",
        ):
            continue
        if ev.get("kind") == "MessageEvent" and ev.get("source") == "agent":
            content = (ev.get("llm_message") or {}).get("content") or []
            text = " ".join(str(x.get("text", "")) for x in content if isinstance(x, dict)).strip()
            markers = ("[ИТОГ QA]", "[БЛОКЕР QA]") if qa else ("[ИТОГ #509]", "[БЛОКЕР #509]")
            # A control marker is a prefix, not prose (e.g. "не [БЛОКЕР QA]").
            if text and not text.startswith(markers):
                return ev.get("id")
        break
    return None


QA_READ_PROBE = "Проверь фактический доступ: один вызов file_editor view только для QA_PROGRESS.md в корне своего workspace. Не обходи отказ; при отказе приведи ошибку инструмента. Ручная пауза обязательна."


def ledger_probe(events):
    # Exactly the known pseudo-blocker; no generic removal of blocker semantics.
    messages = [e for e in events if e.get("kind") not in ("ConversationStateUpdateEvent",)]
    if not messages:
        return None
    e = messages[0]
    if e.get("kind") != "MessageEvent" or e.get("source") != "agent":
        return None
    text = " ".join(
        x.get("text", "")
        for x in (e.get("llm_message") or {}).get("content", [])
        if isinstance(x, dict)
    ).strip()
    if not (
        text.startswith("[БЛОКЕР QA]")
        and "Жду разрешения хост-рантайма на чтение QA_PROGRESS.md" in text
    ):
        return None
    if any(
        t in text.lower()
        for t in ("permission denied", "eacces", "403", "errno", "отказано в доступе")
    ):
        return None
    return e.get("id")


def issue_open():
    req = Request(
        "https://api.github.com/repos/alchemmist/monori/issues/509",
        headers={"User-Agent": "socrat-monori-continuation"},
    )
    with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=10) as r:
        j = json.load(r)
    return j.get("number") == 509 and j.get("state") == "open" and j.get("locked") is False


NUDGE = (
    "Продолжай задачу #509 по-русски. Предыдущий текстовый ответ не доказательство завершения. "
    "Первым действием через инструмент прочитай актуальный статус своих PR и комментарии issue. "
    "Уже принятые изменения не дублируй. Для открытого PR: CI и независимые ревью на текущем SHA, ответ перед resolve. "
    "Если предыдущий PR уже слит владельцем, выбери следующий отдельный "
    "воспроизводимый пробел на свежем main. "
    "Если ждёшь CI, не запускай второй такой PR. Не мержи. "
    "Фиксируй проверенные результаты в checkpoint. "
    "При завершении всего объёма начни ответ с [ИТОГ #509] и приложи проверяемые ссылки; "
    "при реальном внешнем препятствии начни ответ с [БЛОКЕР #509] и укажи факт. Не выдавай план за результат."
)


QA_NUDGE = "Продолжай QA автономно, без повторного подтверждения владельца. Используй QA_PUBLICATION.md из своего workspace. Делегируй следующую конкретную работу ролям: публикуй проверенные issues с безопасными PNG, после партии исправляй каждый issue отдельным PR и проверяй CI/reviews. Не мержи. Не дублируй опубликованные issues. Только при внешнем блокере начни ответ ровно с [БЛОКЕР QA] и объясни причину. Только при завершении всей задачи начни ответ с [ИТОГ QA] и приложи доказательства."


def bridge_disconnected(event):
    detail = event.get("detail", "")
    return (
        event.get("kind") == "ConversationErrorEvent"
        and event.get("code") == "LLMServiceUnavailableError"
        and "model group 'o-deepseek'" in detail
        and "Connection error" in detail
    )


def bridge_ready():
    try:
        return bool(
            socket.getaddrinfo(
                "deeperseeker-ready.deeperseeker.svc.cluster.local.", 4000, type=socket.SOCK_STREAM
            )
        )
    except socket.gaierror:
        return False


def client(cid):
    url = "http://127.0.0.1:8000/api/conversations/" + str(uuid.UUID(cid))

    def api(suffix="", method="GET", data=None):
        key = Path("/session-key").read_text().strip()
        req = Request(
            url + suffix,
            method=method,
            headers={"X-Session-API-Key": key, "Content-Type": "application/json"},
            data=json.dumps(data).encode() if data else None,
        )
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=15) as r:
            return json.load(r)

    return api


WORKER_NUDGE = (
    "Предыдущий ответ содержит только план. Выполни следующий шаг "
    "в своём worktree инструментом. Если закончил, укажи проверяемый результат "
    "и запиши его в PROGRESS.md; при реальном препятствии укажи причину. Не мержи."
)


def pending_worker(status, events, now):
    for e in events:
        if e["kind"] == "ConversationStateUpdateEvent":
            continue
        if status == "error":
            reset = retry_parallel(e)
            if reset and now >= reset:
                return ("parallel", e["id"])
        if status == "finished" and e["kind"] == "MessageEvent" and e.get("source") == "agent":
            text = " ".join(
                x.get("text", "") for x in e["llm_message"]["content"] if isinstance(x, dict)
            ).strip()
            if (
                len(text) < 800
                and re.match(
                    r"^(I (need to|will|should) |Next I will |Мне (нужно|надо) |Сначала я )",
                    text,
                    re.IGNORECASE,
                )
                and not re.search(
                    r"blocked|блокер|denied|permission|approval|разрешени|https?://",
                    text,
                    re.IGNORECASE,
                )
            ):
                return ("plan", e["id"])
        break
    return None


def registry_rows(parent: str, directory: str) -> list[tuple[str, types.FunctionType, str]]:
    """Return registered (id, api, status) rows; ids come from the registry only."""
    # Registry stores current ids; never discover workers from arbitrary text.
    rows = []
    for f in sorted(Path(directory).glob("*.json")):
        r = json.loads(f.read_text())
        cid = str(uuid.UUID(r["id"]))
        api = client(cid)
        child = api()
        if child.get("parent_conversation_id") != parent:
            raise ValueError("wrong parent")
        rows.append((cid, api, child["execution_status"]))
    return rows


def nudge_worker(
    cid: str, api: types.FunctionType, action: tuple[str, str], tracker: Tracker
) -> None:
    """Nudge a stalled worker and record its exponential backoff."""
    failures = tracker["failures"]
    delay = tracker["delay"]
    failures[cid] = failures.get(cid, 0) + 1
    delay[cid] = tracker["now"] + min(3600, 120 * 2 ** min(5, failures[cid] - 1))
    result = (
        api("/run", "POST")
        if action[0] == "parallel"
        else api(
            "/events",
            "POST",
            {"role": "user", "content": [{"type": "text", "text": WORKER_NUDGE}], "run": True},
        )
    )
    print("worker continuation", cid, action[0], bool(result.get("success")), flush=True)


def worker_step(
    parent_api: types.FunctionType,
    cid: str,
    api: types.FunctionType,
    st: str,
    tracker: Tracker,
) -> tuple[str, str] | str:
    """Return 'skip'/'abort' when the pass should move on, else the action to take."""
    attempted = tracker["attempted"]
    delay = tracker["delay"]
    now = tracker["now"]
    if delay.get(cid, 0) > now:
        return "skip"
    ev = api("/events/search?sort_order=TIMESTAMP_DESC&limit=12")["items"]
    if st == "error":
        return (
            "abort"
            if busy_resume(
                cid,
                api,
                ev,
                now,
                lambda: parent_api()["execution_status"] in ("running", "finished"),
            )
            else "skip"
        )
    action: tuple[str, str] | None = pending_worker(st, ev, now)
    if not action or action in attempted:
        return "skip"
    if api()["execution_status"] != st or parent_api()["execution_status"] not in (
        "running",
        "finished",
    ):
        return "abort"
    return action


def monitor_workers(parent, directory):
    attempted: set[tuple[str, str]] = set()
    delay: dict[str, float] = {}
    failures: dict[str, int] = {}
    parent_api = client(parent)
    while True:
        try:
            if parent_api()["execution_status"] not in ("running", "finished"):
                continue
            rows = registry_rows(parent, directory)
            if any(st not in ("error", "finished") for _, _, st in rows):
                continue
            for cid, api, st in rows:
                tracker: Tracker = {
                    "attempted": attempted,
                    "failures": failures,
                    "delay": delay,
                    "now": time.time(),
                }
                result = worker_step(parent_api, cid, api, st, tracker)
                if result == "skip":
                    continue
                if result == "abort":
                    break
                action = cast("tuple[str, str]", result)
                attempted.add(action)
                nudge_worker(cid, api, action, tracker)
                break
        except Exception as exc:
            print("worker check:", type(exc).__name__, flush=True)
        finally:
            time.sleep(45)


def bridge_action(
    ev: dict[str, object], *, bridge_was_down: bool, attempted: str | None
) -> tuple[str | None, bool]:
    """One continuation on a down -> ready bridge transition, else carry state."""
    # One run on a down -> ready transition; no credential probes, no blind retries.
    if not bridge_ready():
        return None, True
    if bridge_was_down and ev.get("id") != attempted:
        return "bridge_restored", False
    return None, bridge_was_down


def post_action(api: types.FunctionType, action: str, *, qa: bool) -> object:
    """Post the nudge or run action to the conversation API."""
    if action in ("unfinished", "ledger_probe"):
        payload = QA_READ_PROBE if action == "ledger_probe" else QA_NUDGE if qa else NUDGE
        return api(
            "/events",
            "POST",
            {"role": "user", "content": [{"type": "text", "text": payload}], "run": True},
        )
    return api("/run", "POST")


def bridge_gate(*, qa: bool, status: str, ev: dict[str, object], conv: dict[str, object]) -> bool:
    """Report whether the error came from the bridged deepseek model."""
    agent = cast("dict[str, object]", conv["agent"])
    llm = cast("dict[str, object]", agent["llm"])
    return (
        not qa
        and status == "error"
        and bridge_disconnected(ev)
        and llm["model"] == "openai/o-deepseek"
    )


def ledger_step(events: object, *, qa: bool, state: MonitorState) -> tuple[str | None, str | None]:
    """One-time QA ledger read probe; returns (action, eid)."""
    if qa and not state.probed:
        probe = ledger_probe(events)
        if probe and probe != state.attempted:
            return "ledger_probe", probe
    return None, None


def unfinished_step(
    events: object, *, qa: bool, state: MonitorState, now: float
) -> tuple[str | None, str | None]:
    """Final-message continuation; returns (action, eid) and defers repeating for 5 minutes."""
    eid = final_message(events, qa)
    if eid and eid != state.attempted:
        state.after = now + 300
        if qa or issue_open():
            return "unfinished", eid
    return None, eid


def next_step(
    ctx: Conversation, status: str, *, qa: bool, state: MonitorState, now: float
) -> tuple[str, str] | None:
    """Decide the continuation action; returns (action, eid) when one is due."""
    cid = ctx["cid"]
    api = ctx["api"]
    conv = ctx["conv"]
    events = api("/events/search?sort_order=TIMESTAMP_DESC&limit=8")["items"]
    ev = events[0] if events else {}
    eid = ev.get("id")
    action = None
    if eligible(status, ev):
        action = "iteration"
    elif bridge_gate(qa=qa, status=status, ev=ev, conv=conv):
        action, state.bridge_was_down = bridge_action(
            ev, bridge_was_down=state.bridge_was_down, attempted=state.attempted
        )
    elif status == "error":
        busy_resume(cid, api, events, now)
    elif status == "finished":
        action, eid2 = ledger_step(events, qa=qa, state=state)
        if action is None:
            action, eid = unfinished_step(events, qa=qa, state=state, now=now)
        else:
            eid = eid2
    if action and eid and eid != state.attempted and api()["execution_status"] == status:
        return action, eid
    return None


def run_action(
    api: types.FunctionType, selected: tuple[str, str], *, qa: bool, state: MonitorState
) -> None:
    """Apply the selected continuation and record the acknowledgment."""
    action, eid = selected
    if action == "ledger_probe":
        state.probed = True
    state.attempted = eid
    ok = cast("dict[str, object]", post_action(api, action, qa=qa))
    print("continue", action, eid, "acknowledged", bool(ok.get("success")), flush=True)


def monitor(cid, qa=False):
    api = client(cid)
    state = MonitorState()
    while True:
        try:
            conv = api()
            status = conv["execution_status"]
            now = time.time()
            if status in ("finished", "error") and now >= state.after:
                ctx: Conversation = {
                    "cid": cid,
                    "api": api,
                    "conv": cast("dict[str, object]", conv),
                }
                selected = next_step(ctx, status, qa=qa, state=state, now=now)
                if selected is not None:
                    run_action(api, selected, qa=qa, state=state)
            elif status == "running" and state.last_parallel and now > state.after + 600:
                state.parallel_failures = 0
        except Exception as exc:
            print("continuation check:", type(exc).__name__, flush=True)
        time.sleep(30)


if __name__ == "__main__":
    import threading

    if os.getenv("QA_CONVERSATION_ID"):
        threading.Thread(
            target=monitor, args=(os.environ["QA_CONVERSATION_ID"], True), daemon=True
        ).start()
    for env, folder in [
        ("CONVERSATION_ID", "/mutation-registry"),
        ("QA_CONVERSATION_ID", "/qa-registry"),
    ]:
        if os.getenv(env) and Path(folder).is_dir():
            threading.Thread(
                target=monitor_workers, args=(os.environ[env], folder), daemon=True
            ).start()
    monitor(os.environ["CONVERSATION_ID"])
