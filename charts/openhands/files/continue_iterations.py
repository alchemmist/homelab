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


def final_message(events,qa=False):
    # Never infer an agent finish from arbitrary user/file/tool text.
    for ev in events:
        if ev.get('kind')=='ConversationStateUpdateEvent' and ev.get('key') in ('execution_status','stats'):continue
        if ev.get('kind')=='MessageEvent' and ev.get('source')=='agent':
            content=(ev.get('llm_message') or {}).get('content') or []
            text=' '.join(str(x.get('text','')) for x in content if isinstance(x,dict)).strip()
            markers=('[ИТОГ QA]','[БЛОКЕР QA]') if qa else ('[ИТОГ #509]','[БЛОКЕР #509]')
            # A control marker is a prefix, not prose (e.g. "не [БЛОКЕР QA]").
            if text and not text.startswith(markers):return ev.get('id')
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
       'При завершении всего объёма начни ответ с [ИТОГ #509] и приложи проверяемые ссылки; '
       'при реальном внешнем препятствии начни ответ с [БЛОКЕР #509] и укажи факт. Не выдавай план за результат.')


QA_NUDGE=('Продолжай QA автономно, без повторного подтверждения владельца. Используй QA_PUBLICATION.md из своего workspace. Делегируй следующую конкретную работу ролям: публикуй проверенные issues с безопасными PNG, после партии исправляй каждый issue отдельным PR и проверяй CI/reviews. Не мержи. Не дублируй опубликованные issues. Только при внешнем блокере начни ответ ровно с [БЛОКЕР QA] и объясни причину. Только при завершении всей задачи начни ответ с [ИТОГ QA] и приложи доказательства.')

def monitor(cid,qa=False):
    cid=str(uuid.UUID(cid))
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
                elif status=='finished' and (eid:=final_message(events,qa)) and eid!=attempted:
                    after=now+300
                    if qa or issue_open():action='unfinished'
                if action and eid and eid!=attempted and api()['execution_status']==status:
                    attempted=eid
                    ok=(api('/events','POST',{'role':'user','content':[{'type':'text','text':QA_NUDGE if qa else NUDGE}],'run':True}) if action=='unfinished' else api('/run','POST'))
                    print('continue',action,eid,'acknowledged',bool(ok.get('success')),flush=True)
            elif status=='running' and last_parallel and now>after+600:parallel_failures=0
        except Exception as exc:print('continuation check:',type(exc).__name__,flush=True)
        time.sleep(30)
if __name__=='__main__':
    import threading
    if os.getenv('QA_CONVERSATION_ID'): threading.Thread(target=monitor,args=(os.environ['QA_CONVERSATION_ID'],True),daemon=True).start()
    monitor(os.environ['CONVERSATION_ID'])
