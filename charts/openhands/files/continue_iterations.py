"""Opt-in continuation for exactly one conversation; no model or GitHub credentials."""
import json
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

def main():
    cid=str(uuid.UUID(os.environ['CONVERSATION_ID']))
    url='http://127.0.0.1:8000/api/conversations/'+cid
    def api(suffix='',method='GET'):
        key=Path('/session-key').read_text().strip();req=Request(url+suffix,method=method,headers={'X-Session-API-Key':key})
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=10) as r:return json.load(r)
    attempted=None
    while True:
        try:
            status=api()['execution_status']
            if status=='error':
                events=api('/events/search?sort_order=TIMESTAMP_DESC&limit=1')['items'];ev=events[0] if events else {}
                if eligible(status,ev) and ev['id']!=attempted and api()['execution_status']=='error':
                    attempted=ev['id'];ok=api('/run','POST');print('continued iteration boundary' if ok.get('success') else 'resume not acknowledged',attempted,flush=True)
        except Exception as exc:print('continuation check:',type(exc).__name__,flush=True)
        time.sleep(60)
if __name__=='__main__':main()
