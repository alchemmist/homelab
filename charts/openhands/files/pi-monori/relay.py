"""Loopback-only model relay. No arbitrary URL, model, auth header or redirect."""
import http.client,json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
slot=threading.BoundedSemaphore(1)
class Handler(BaseHTTPRequestHandler):
 """HTTP handler relaying chat completions to the in-cluster model."""

 def log_message(self,*a):pass
 def do_POST(self):
  if self.path!='/v1/chat/completions' or self.headers.get('Transfer-Encoding'):self.send_error(404);return
  n=int(self.headers.get('Content-Length',0));self.connection.settimeout(650)
  if not 0<n<=180000:self.send_error(413);return
  try:j=json.loads(self.rfile.read(n));assert j['model']=='v-deepseek-uc' and isinstance(j['messages'],list) and not set(j)&{'api_base','api_key','fallbacks','extra_headers','metadata'}
  except (ValueError,KeyError,AssertionError):self.send_error(400);return
  if not slot.acquire(timeout=30):self.send_error(429);return
  conn=http.client.HTTPConnection('litellm.llm.svc.cluster.local',4000,timeout=620)
  try:
   conn.request('POST','/v1/chat/completions',json.dumps(j).encode(),{'Authorization':'Bearer '+Path('/model/api-key').read_text().strip(),'Content-Type':'application/json'});r=conn.getresponse();self.send_response(r.status);self.send_header('Content-Type',r.getheader('Content-Type','application/json'));self.end_headers()
   if r.status>=400:self.wfile.write(json.dumps({'error':{'message':'LiteLLM HTTP '+str(r.status),'type':'upstream_error'}}).encode());return
   while data:=r.read1(16384):self.wfile.write(data);self.wfile.flush()
  finally:conn.close();slot.release()
ThreadingHTTPServer(('127.0.0.1',4188),Handler).serve_forever()
