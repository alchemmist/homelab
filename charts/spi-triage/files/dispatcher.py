"""Single durable wake reservation; never hold database locks during HTTP."""
import json
import threading
import urllib.request

DISPATCH_URL = 'http://n8n.automation.svc.cluster.local/webhook/spi-incident-triage-dispatch'

class Dispatcher:
    def __init__(self, store, token, enabled=False, post=None):
        self.store=store
        self.token=token
        self.enabled=enabled
        self.post=post or self._post
        self.wake=threading.Event()
        self.stopped=threading.Event()
        self.thread=None

    def _post(self):
        request=urllib.request.Request(DISPATCH_URL, data=b'{}',
            headers={'X-Worker-Token':self.token,'Content-Type':'application/json'}, method='POST')
        # Do not follow redirects with worker credentials.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
            if not 200 <= response.status < 300:raise OSError('Dispatch rejected')

    def signal(self):
        self.wake.set()

    def tick(self):
        if not self.enabled:return None
        reservation, deadline=self.store.reserve_dispatch()
        if reservation:
            try:
                self.post()
                event='dispatch_sent'
            except Exception:
                # A failed response does not prove that n8n did not start.
                event='dispatch_unconfirmed'
            print(json.dumps({'component':'spi-triage','event':event}),flush=True)
            # Claim can acknowledge while POST is in flight. Never recreate it.
            return 0
        return deadline

    def _run(self):
        import time
        while not self.stopped.is_set():
            self.wake.clear()
            try:deadline=self.tick()
            except Exception:
                print(json.dumps({'component':'spi-triage','event':'dispatch_internal_error'}),flush=True)
                deadline=time.time()+30
            timeout=None if deadline is None else max(0.05,deadline-time.time())
            self.wake.wait(timeout)

    def start(self):
        if self.enabled and self.thread is None:
            self.thread=threading.Thread(target=self._run, name='spi-dispatch', daemon=True)
            self.thread.start()

    def stop(self):
        self.stopped.set();self.signal()
        if self.thread:self.thread.join(timeout=12)
