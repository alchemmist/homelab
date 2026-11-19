"""Opt-in continuation for exactly one conversation; no model or GitHub credentials."""
import json
from datetime import datetime, timezone
import re
import os
import time
import uuid
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):return None

def eligible(status,event):
    return (status=='error' and event.get('kind')=='ConversationErrorEvent' and
            event.get('source')=='environment' and event.get('code')=='MaxIterationsReached' and bool(event.get('id')))

def retry_parallel(event):
    if event.get('kind')!='ConversationErrorEvent' or event.get('source')!='environment':return None
    text=event.get('detail','')
    if 'RateLimitError' not in text or 'Limit type: max_parallel_requests.' not in text:return None
    m=re.search(r'Limit resets at: (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC',text)
    return datetime.strptime(m[1],'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()+15 if m else None


def final_message(events):
    # Never infer an agent finish from arbitrary user/file/tool text.
    for ev in events:
        if ev.get('kind')=='ConversationStateUpdateEvent' and ev.get('key') in ('execution_status','stats'):continue
        if ev.get('kind')=='MessageEvent' and ev.get('source')=='agent':
            content=(ev.get('llm_message') or {}).get('content') or []
            text=' '.join(str(x.get('text','')) for x in content if isinstance(x,dict)).strip()
            if text and not any(mark in text for mark in ('[ИТОГ #509]','[БЛОКЕР #509]')):return ev.get('id')
        break
    return None


def issue_open():
    req=Request('https://api.github.com/repos/alchemmist/monori/issues/509',headers={'User-Agent':'socrat-monori-continuation'})
    with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=10) as r:j=json.load(r)
    return j.get('number')==509 and j.get('state')=='open' and j.get('locked') is False

NUDGE=('Продолжай задачу #509 по-русски. Предыдущий текстовый ответ не доказательство завершения. '
       'Первым действием через инструмент прочитай актуальный статус своих PR и комментарии issue. '
       'Уже принятые изменения не дублируй. Для открытого PR: CI и независимые ревью на текущем SHA, ответ перед resolve. '
       'Если предыдущий PR уже слит владельцем, выбери следующий отдельный воспроизводимый пробел на свежем main. '
       'Если ждёшь CI, не запускай второй такой PR. Не мержи. Фиксируй проверенные результаты в checkpoint. '
       'При завершении всего объёма приложи проверяемые ссылки и отметь [ИТОГ #509]; '
       'при реальном внешнем препятствии укажи факт и [БЛОКЕР #509]. Не выдавай план за результат.')


def main():
    cid=str(uuid.UUID(os.environ['CONVERSATION_ID']))
    url='http://127.0.0.1:8000/api/conversations/'+cid
    def api(suffix='',method='GET',data=None):
        key=Path('/session-key').read_text().strip();req=Request(url+suffix,method=method,headers={'X-Session-API-Key':key,'Content-Type':'application/json'},data=json.dumps(data).encode() if data else None)
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=15) as r:return json.load(r)
    attempted=None; after=0; parallel_failures=0; last_parallel=None
    while True:
        try:
            status=api()['execution_status'];now=time.time()
            if status in ('finished','error') and now>=after:
                events=api('/events/search?sort_order=TIMESTAMP_DESC&limit=8')['items'];ev=events[0] if events else {};eid=ev.get('id');action=None
                if eligible(status,ev):action='iteration'
                elif status=='error' and (reset:=retry_parallel(ev)) is not None:
                    if last_parallel!=eid:
                        last_parallel=eid;parallel_failures+=1;after=max(reset,now+min(900,30*2**min(parallel_failures-1,5)))
                    if now>=after:action='parallel'
                elif status=='finished' and (eid:=final_message(events)) and eid!=attempted:
                    after=now+300
                    if issue_open():action='unfinished'
                if action and eid and eid!=attempted and api()['execution_status']==status:
                    attempted=eid
                    ok=(api('/events','POST',{'role':'user','content':[{'type':'text','text':NUDGE}],'run':True}) if action=='unfinished' else api('/run','POST'))
                    print('continue',action,eid,'acknowledged',bool(ok.get('success')),flush=True)
            elif status=='running' and last_parallel and now>after+600:parallel_failures=0
        except Exception as exc:print('continuation check:',type(exc).__name__,flush=True)
        time.sleep(30)
if __name__=='__main__':main()
