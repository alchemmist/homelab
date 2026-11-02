#!/usr/bin/env python3
"""Anonymous, read-only Nature performance/branding checks. No login/owner factors.
No screenshots, private HTML, traces or cookies are persisted. --run required.
"""
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run',action='store_true')
parser.add_argument('--delay-hq',action='store_true',help='Also hold HQ locally for 5s to verify usable preview-only login')
parser.add_argument('--public-edge',choices=['109.173.40.247','176.98.185.59'])
args=parser.parse_args()
if not args.run:parser.error('--run required')
import hashlib,json
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]/'deploy/authentik/quiet-mono'
assets=json.loads((root/'assets.json').read_text());photos=json.loads((root/'nature.json').read_text())['photos']
css_hashes={assets[p['sceneCss']]['sha256'] for p in photos}
BASE='https://auth.socrat.alchemmist.xyz'
with sync_playwright() as p:
 for edge in ([args.public_edge] if args.public_edge else ['109.173.40.247','176.98.185.59']):
  browser=p.chromium.launch(args=['--host-resolver-rules=MAP auth.socrat.alchemmist.xyz '+edge])
  for width,height,variant in [(1440,960,'desktop'),(390,844,'mobile')]:
   context=browser.new_context(viewport={'width':width,'height':height});page=context.new_page();responses=[];errors=[]
   page.on('response',lambda r:responses.append(r) if '/-/quiet-mono/v1/' in r.url else None)
   page.on('pageerror',lambda e:errors.append(True))
   page.goto(BASE+'/if/flow/default-authentication-flow/');page.locator('input[name=uidField]').wait_for();page.wait_for_timeout(600)
   scenes=[r for r in responses if r.url.endswith('/nature/scene.css')];assert len(scenes)==1,'One random CSS selection per document'
   scene=scenes[0];assert scene.status==200 and scene.headers['cache-control']=='no-store'
   assert hashlib.sha256(scene.body()).hexdigest() in css_hashes
   photo=next(p for p in photos if p['id']==scene.headers['x-quiet-mono-scene'])
   key=photo[variant+'Avif'];item=assets[key]
   image=next(r for r in responses if r.url.endswith('-'+Path(item['path']).name))
   assert image.status==200 and image.headers['content-type']=='image/avif'
   assert 'immutable' in image.headers['cache-control'] and hashlib.sha256(image.body()).hexdigest()==item['sha256']
   full=[r for r in responses if r.url.endswith(('.avif','.webp')) and '-nature-' in r.url]
   assert len(full)==1,'Only one full-size photograph; no desktop download on mobile'
   style=page.evaluate("getComputedStyle(document.body,'::before').backgroundImage")
   assert 'data:image/webp;base64,' in style and Path(item['path']).name in style
   assert page.locator('ak-drawer#flow-drawer').evaluate('e=>getComputedStyle(e).backgroundImage')=='none'
   timing=page.evaluate("performance.getEntriesByType('resource').filter(x=>x.name.endsWith('.avif')).map(x=>({start:Math.round(x.startTime),end:Math.round(x.responseEnd),bytes:x.transferSize}))[0]")
   # Re-request the already chosen immutable image using the browser HTTP cache.
   page.evaluate("async url=>{await(await fetch(url,{mode:'no-cors',credentials:'include'})).arrayBuffer()}",image.url)
   cached=page.evaluate("url=>performance.getEntriesByName(url).at(-1).transferSize",image.url)
   assert cached==0,'Previously selected image must reuse browser cache'
   count=len(responses);page.wait_for_timeout(1200);assert len(responses)==count,'No slideshow/background rotation'
   assert not errors
   print('PASS',edge,variant,'one scene CSS + one AVIF; same-photo inline preview; warm image transfer 0 bytes;',timing,flush=True)
   context.close()
  context=browser.new_context();page=context.new_page();scenes=set()
  for i in range(12):
   r=page.goto(BASE+'/-/quiet-mono/v1/nature/scene.css')
   assert r.status==200 and hashlib.sha256(r.body()).hexdigest() in css_hashes
   scenes.add(r.headers['x-quiet-mono-scene'])
  assert len(scenes)>=3
  for path in ['scene.css','desktop','mobile']:
   assert context.request.post(BASE+'/-/quiet-mono/v1/nature/'+path).status==403
  # Backward-compatible non-AVIF native clients receive the original pinned WebP.
  r=context.request.get(BASE+'/-/quiet-mono/v1/nature/mobile',headers={'Accept':'image/webp'},max_redirects=0)
  assert r.status==302 and r.headers['cache-control']=='no-store'
  fallback=context.request.get(BASE+r.headers['location'])
  assert fallback.status==200 and fallback.headers['content-type']=='image/webp'
  assert hashlib.sha256(fallback.body()).hexdigest() in {assets[p['mobile']]['sha256'] for p in photos}
  print('PASS',edge,'random scenes:',len(scenes),'/12; POST denied; pinned WebP fallback',flush=True)
  context.close();browser.close()


if args.delay_hq:
 import asyncio
 from playwright.async_api import async_playwright
 async def preview_only():
  async with async_playwright() as p:
   for edge in ([args.public_edge] if args.public_edge else ['109.173.40.247','176.98.185.59']):
    browser=await p.chromium.launch(args=['--host-resolver-rules=MAP auth.socrat.alchemmist.xyz '+edge])
    for width in [1440,390]:
     page=await browser.new_page(viewport={'width':width,'height':960})
     release=asyncio.Event();pending=[]
     async def hold(route):
      pending.append(True)
      await release.wait()
      await route.continue_()
     await page.route('**/*-nature-*.avif',hold)
     try:
      await page.goto(BASE+'/if/flow/default-authentication-flow/',wait_until='domcontentloaded')
      await page.locator('input[name=uidField]').wait_for()
      assert pending and not release.is_set()
      assert await page.locator('input[name=uidField]').is_enabled()
      assert 'data:image/webp;base64,' in await page.evaluate("getComputedStyle(document.body,'::before').backgroundImage")
      await page.wait_for_timeout(5000)
      assert await page.locator('input[name=uidField]').is_enabled()
      print('PASS preview-only native login usable with HQ held for 5s',edge,width,flush=True)
     finally:
      release.set();await page.wait_for_timeout(500);await page.close()
    await browser.close()
 asyncio.run(preview_only())
