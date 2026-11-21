"""Opt-in continuation for exactly one conversation; no model or GitHub credentials."""
import json
from datetime import datetime, timezone
import re
import os
import time
import socket
import sqlite3
from contextlib import closing
from collections.abc import Callable
from typing import Protocol, cast
import uuid
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):return None


class _ConvoApi(Protocol):
    def __call__(
        self, suffix: str = ..., method: str = ..., data: dict[str, object] | None = ...
    ) -> dict[str, object]: ...



class _Condition(Protocol):
    def __bool__(self) -> bool: ...


def eligible(status:str,event:dict[str,object]):
    return (status=='error' and event.get('kind')=='ConversationErrorEvent' and
            event.get('source')=='environment' and event.get('code')=='MaxIterationsReached' and bool(event.get('id')))

def retry_parallel(event:dict[str,object]):
    if event.get('kind')!='ConversationErrorEvent' or event.get('source')!='environment':return None
    text=cast("str",event.get('detail',''))
    if event.get('code','LLMRateLimitError')!='LLMRateLimitError' or 'RateLimitError' not in text:return None
    if re.search(r'\bmax_parallel_requests=[1-9]\d* requests in flight\b',text):return 0
    if 'Limit type: max_parallel_requests.' not in text:return None
    m=re.search(r'Limit resets at: (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC',text)
    return datetime.strptime(m[1],'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()+15 if m else None


def busy_resume(cid:str,api:_ConvoApi,events:list[dict[str,object]],now:float,
        allowed:Callable[[],bool]=lambda:True,path:str='/wait-state/waits.db'):
    """Persist only scheduling metadata. Never replay a tool call or user message."""
    ev=next((e for e in events if e['kind']!='ConversationStateUpdateEvent'),{})
    reset=retry_parallel(ev);eid=ev.get('id')
    if reset is None or not eid:return False
    c=api()
    if c['execution_status']!='error':return False
    model=cast("dict[str, object]", cast("dict[str, object]", c['agent'])['llm'])['model']
    group=re.search(r"model group '([a-zA-Z0-9_.-]+)'",cast("str",ev['detail']))
    if group:model='openai/'+group[1]
    with closing(sqlite3.connect(path,timeout=8)) as db, db:
        db.execute('create table if not exists waits(cid text primary key, model text, eid text, due real, n integer)')
        db.execute('create table if not exists gates(model text primary key, until_ts real)')
        db.execute('begin immediate')
        row=db.execute('select eid,due,n from waits where cid=?',(cid,)).fetchone()
        if not row or row[0]!=eid:
            n=min(5,row[2]+1) if row and now-row[1]<1800 else 0
            due=max(reset,now+min(900,60*2**n));db.execute('insert or replace into waits values(?,?,?,?,?)',(cid,model,eid,due,n));return False
        gate=db.execute('select until_ts from gates where model=?',(model,)).fetchone()
        if now<row[1] or (gate and now<gate[0]):return False
        if not allowed() or api()['execution_status']!='error':return False
        search=api('/events/search?sort_order=TIMESTAMP_DESC&limit=12')['items']
        latest=cast("list[dict[str, object]]",search)
        if next((e.get('id') for e in latest if e['kind']!='ConversationStateUpdateEvent'),None)!=eid:return False
        # Commit cooldown before HTTP: lost acknowledgement cannot trigger a burst.
        db.execute('update waits set due=? where cid=?',(now+900,cid));db.execute('insert or replace into gates values(?,?)',(model,now+60));db.commit()
        ok=api('/run','POST').get('success');print('capacity resume',cid,model,bool(ok),flush=True);return bool(ok)

def final_message(events:list[dict[str,object]],qa:_Condition=False):
    # Never infer an agent finish from arbitrary user/file/tool text.
    for ev in events:
        if ev.get('kind')=='ConversationStateUpdateEvent' and ev.get('key') in ('execution_status','stats'):continue
        if ev.get('kind')=='MessageEvent' and ev.get('source')=='agent':
            message=cast("dict[str, object]",ev.get('llm_message') or {})
            content=cast("list[object]",message.get('content') or [])
            text=' '.join(str(x.get('text','')) for x in content if isinstance(x,dict)).strip()
            markers=('[ИТОГ QA]','[БЛОКЕР QA]') if qa else ('[ИТОГ #509]','[БЛОКЕР #509]')
            # A control marker is a prefix, not prose (e.g. "не [БЛОКЕР QA]").
            if text and not text.startswith(markers):return ev.get('id')
        break
    return None


QA_READ_PROBE='Проверь фактический доступ: один вызов file_editor view только для QA_PROGRESS.md в корне своего workspace. Не обходи отказ; при отказе приведи ошибку инструмента. Ручная пауза обязательна.'

def ledger_probe(events:list[dict[str,object]]):
    # Exactly the known pseudo-blocker; no generic removal of blocker semantics.
    messages=[e for e in events if e.get('kind') not in ('ConversationStateUpdateEvent',)]
    if not messages:return None
    e=messages[0]
    if e.get('kind')!='MessageEvent' or e.get('source')!='agent':return None
    text=' '.join(cast("str",x.get('text','')) for x in cast("list[object]",cast("dict[str, object]",e.get('llm_message') or {}).get('content',[])) if isinstance(x,dict)).strip()
    if not (text.startswith('[БЛОКЕР QA]') and 'Жду разрешения хост-рантайма на чтение QA_PROGRESS.md' in text):return None
    if any(t in text.lower() for t in ('permission denied','eacces','403','errno','отказано в доступе')):return None
    return e.get('id')

def issue_open():
    req=Request('https://api.github.com/repos/alchemmist/monori/issues/509',headers={'User-Agent':'socrat-monori-continuation'})
    with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=10) as r:j=json.load(r)
    return j.get('number')==509 and j.get('state')=='open' and j.get('locked') is False

NUDGE=('Продолжай задачу #509 по-русски. Предыдущий текстовый ответ не доказательство завершения. '
       'Первым действием через инструмент прочитай актуальный статус своих PR и комментарии issue. '
       'Уже принятые изменения не дублируй. Для открытого PR: CI и независимые ревью на текущем SHA, ответ перед resolve. '
       'Если предыдущий PR уже слит владельцем, выбери следующий отдельный воспроизводимый пробел на свежем main. '
       'Если ждёшь CI, не запускай второй такой PR. Не мержи. Фиксируй проверенные результаты в checkpoint. '
       'При завершении всего объёма начни ответ с [ИТОГ #509] и приложи проверяемые ссылки; '
       'при реальном внешнем препятствии начни ответ с [БЛОКЕР #509] и укажи факт. Не выдавай план за результат.')


QA_NUDGE=('Продолжай QA автономно, без повторного подтверждения владельца. Используй QA_PUBLICATION.md из своего workspace. Делегируй следующую конкретную работу ролям: публикуй проверенные issues с безопасными PNG, после партии исправляй каждый issue отдельным PR и проверяй CI/reviews. Не мержи. Не дублируй опубликованные issues. Только при внешнем блокере начни ответ ровно с [БЛОКЕР QA] и объясни причину. Только при завершении всей задачи начни ответ с [ИТОГ QA] и приложи доказательства.')

def bridge_disconnected(event:dict[str,object]):
    detail=cast("str",event.get('detail',''))
    return (event.get('kind')=='ConversationErrorEvent' and event.get('code')=='LLMServiceUnavailableError'
            and "model group 'o-deepseek'" in detail and 'Connection error' in detail)

def bridge_ready():
    try:return bool(socket.getaddrinfo('deeperseeker-ready.deeperseeker.svc.cluster.local.',4000,type=socket.SOCK_STREAM))
    except socket.gaierror:return False

def client(cid:str):
    url='http://127.0.0.1:8000/api/conversations/'+str(uuid.UUID(cid))
    def api(suffix:str='',method:str='GET',data:dict[str,object]|None=None):
        key=Path('/session-key').read_text().strip();req=Request(url+suffix,method=method,headers={'X-Session-API-Key':key,'Content-Type':'application/json'},data=json.dumps(data).encode() if data else None)
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=15) as r:return json.load(r)
    return api

WORKER_NUDGE='Предыдущий ответ содержит только план. Выполни следующий шаг в своём worktree инструментом. Если закончил, укажи проверяемый результат и запиши его в PROGRESS.md; при реальном препятствии укажи причину. Не мержи.'

def pending_worker(status:str,events:list[dict[str,object]],now:float):
    for e in events:
        if e['kind']=='ConversationStateUpdateEvent':continue
        if status=='error':
            reset=retry_parallel(e)
            if reset and now>=reset:return ('parallel',e['id'])
        if status=='finished' and e['kind']=='MessageEvent' and e.get('source')=='agent':
            text=' '.join(cast("str",x.get('text','')) for x in cast("list[object]",cast("dict[str, object]",e['llm_message'])['content']) if isinstance(x,dict)).strip()
            if len(text)<800 and re.match(r'^(I (need to|will|should) |Next I will |Мне (нужно|надо) |Сначала я )',text,re.I) and not re.search(r'blocked|блокер|denied|permission|approval|разрешени|https?://',text,re.I):return ('plan',e['id'])
        break
    return None

def monitor_workers(parent:str,directory:str):
    # Registry stores current ids; never discover workers from arbitrary text.
    attempted=set();delay:dict[str,float]={};failures:dict[str,int]={};parent_api=client(parent)
    while True:
        try:
            if parent_api()['execution_status'] not in ('running','finished'):continue
            rows=[]
            for f in sorted(Path(directory).glob('*.json')):
                r=json.loads(f.read_text());cid=str(uuid.UUID(r['id']));api=client(cid);child=api()
                if child.get('parent_conversation_id')!=parent:raise ValueError('wrong parent')
                rows.append((cid,api,child['execution_status']))
            if any(st not in ('error','finished') for _,_,st in rows):continue
            for cid,api,st in rows:
                now=time.time()
                if delay.get(cid,0)>now:continue
                ev=api('/events/search?sort_order=TIMESTAMP_DESC&limit=12')['items']
                if st=='error':
                    if busy_resume(cid,api,ev,now,lambda: parent_api()['execution_status'] in ('running','finished')):break
                    continue
                action=pending_worker(st,ev,now)
                if not action or action in attempted:continue
                if api()['execution_status']!=st or parent_api()['execution_status'] not in ('running','finished'):break
                attempted.add(action);failures[cid]=failures.get(cid,0)+1;delay[cid]=now+min(3600,120*2**min(5,failures[cid]-1))
                result=api('/run','POST') if action[0]=='parallel' else api('/events','POST',{'role':'user','content':[{'type':'text','text':WORKER_NUDGE}],'run':True})
                print('worker continuation',cid,action[0],bool(result.get('success')),flush=True);break
        except Exception as exc:print('worker check:',type(exc).__name__,flush=True)
        finally:time.sleep(45)

def monitor(cid:str,qa:_Condition=False):
    api=client(cid)
    bridge_was_down=False; probed=False; attempted=None; after:float=0; parallel_failures=0; last_parallel:str|None=None
    while True:
        try:
            conv=api();status=conv['execution_status'];now=time.time()
            if status in ('finished','error') and now>=after:
                events=api('/events/search?sort_order=TIMESTAMP_DESC&limit=8')['items'];ev=events[0] if events else {};eid=ev.get('id');action=None
                if eligible(status,ev):action='iteration'
                elif not qa and status=='error' and bridge_disconnected(ev) and conv['agent']['llm']['model']=='openai/o-deepseek':
                    # One run on a down -> ready transition; no credential probes, no blind retries.
                    if not bridge_ready():bridge_was_down=True
                    elif bridge_was_down and eid!=attempted:
                        bridge_was_down=False;action='bridge_restored'
                elif status=='error':busy_resume(cid,api,events,now)
                elif qa and not probed and status=='finished' and (eid:=ledger_probe(events)) and eid!=attempted:
                    action='ledger_probe'
                elif status=='finished' and (eid:=final_message(events,qa)) and eid!=attempted:
                    after=now+300
                    if qa or issue_open():action='unfinished'
                if action and eid and eid!=attempted and api()['execution_status']==status:
                    if action=='ledger_probe':probed=True
                    attempted=eid
                    ok=(api('/events','POST',{'role':'user','content':[{'type':'text','text':QA_READ_PROBE if action=='ledger_probe' else QA_NUDGE if qa else NUDGE}],'run':True}) if action in ('unfinished','ledger_probe') else api('/run','POST'))
                    print('continue',action,eid,'acknowledged',bool(ok.get('success')),flush=True)
            elif status=='running' and last_parallel and now>after+600:parallel_failures=0
        except Exception as exc:print('continuation check:',type(exc).__name__,flush=True)
        time.sleep(30)
if __name__=='__main__':
    import threading
    if os.getenv('QA_CONVERSATION_ID'): threading.Thread(target=monitor,args=(os.environ['QA_CONVERSATION_ID'],True),daemon=True).start()
    for env,folder in [('CONVERSATION_ID','/mutation-registry'),('QA_CONVERSATION_ID','/qa-registry')]:
        if os.getenv(env) and Path(folder).is_dir():threading.Thread(target=monitor_workers,args=(os.environ[env],folder),daemon=True).start()
    monitor(os.environ['CONVERSATION_ID'])
