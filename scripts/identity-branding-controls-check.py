#!/usr/bin/env python3
"""Read-only live CSS/native-component probes, not owner-session acceptance.

Fresh anonymous browser only. The inspector query exposes a native debug toggle,
but its API must remain denied. The redirect challenge is a local browser-only
layout probe with a blocked .invalid target, not a server auth response. No real
saved HTML, session/context, credentials, screenshots or fixtures are stored.
"""
import argparse
from playwright.sync_api import sync_playwright
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run',action='store_true')
parser.add_argument('--public-edge',choices=['109.173.40.247','109.120.141.97'],default='109.173.40.247')
args=parser.parse_args()
if not args.run:parser.error('--run is required for live read-only UI probes')
BASE='https://auth.socrat.alchemmist.xyz'
with sync_playwright() as p:
 b=p.chromium.launch(args=['--host-resolver-rules=MAP auth.socrat.alchemmist.xyz '+args.public_edge])
 page=b.new_page(viewport={'width':1440,'height':960});errors=[];statuses=[]
 page.on('pageerror',lambda e:errors.append(type(e).__name__))
 page.on('response',lambda r: statuses.append(r.status) if '/flows/inspector/' in r.url else None)
 page.goto(BASE+'/if/flow/default-authentication-flow/?inspector=available');page.locator('input[name=uidField]').wait_for()
 # Normal anonymous login must not show the debug control without its explicit query.
 anonymous=b.new_page();anonymous.goto(BASE+'/if/flow/default-authentication-flow/');anonymous.locator('input[name=uidField]').wait_for()
 assert anonymous.get_by_role('button',name='Open flow inspector',exact=True).count()==0
 anonymous.close()
 toggle=page.get_by_role('button',name='Open flow inspector',exact=True);toggle.wait_for()
 for width,offset in [(1440,24),(390,17)]:
  page.set_viewport_size({'width':width,'height':960});page.wait_for_timeout(250)
  box=toggle.bounding_box();assert abs(box['y']-offset)<1 and abs(width-box['x']-box['width']-offset)<1
  assert box['width']==box['height']==39
  icon=page.locator('ak-flow-inspector-button i');ic=icon.bounding_box();assert ic['width']==ic['height']==18
  assert abs(ic['x']+9-box['x']-19.5)<1 and abs(ic['y']+9-box['y']-19.5)<1
  assert 'data:image/svg+xml' in icon.evaluate('e=>getComputedStyle(e).maskImage')
  print('PASS: actual native magnifier, square hit target, centered 18px icon and viewport offset',width)
 page.set_viewport_size({'width':1440,'height':960});toggle.click();page.wait_for_timeout(1000)
 assert statuses and statuses[-1] in [403,404]
 # Empty local layout box only: no native snapshots/history entries are forged.
 for width in [1440,390]:
  page.set_viewport_size({'width':width,'height':960})
  result=page.locator('ak-flow-inspector').evaluate("""e=>{
   const box=document.createElement('ol');box.className='pf-c-progress-stepper';box.style.height='1000px';
   e.shadowRoot.append(box);
   try{const s=getComputedStyle(box);return {max:s.maxBlockSize,overflow:s.overflowY,height:box.getBoundingClientRect().height}}
   finally{box.remove()}
  }""")
  assert result['max']=='none' and result['overflow']=='visible' and result['height']==1000
  print('PASS: Plan History natural height, no internal scrolling',width)
 page.set_viewport_size({'width':1440,'height':960})
 # Local-only native component probe, not an authentication response or permission grant.
 target='https://example.invalid/quiet-mono-native-control-probe';attempts=[]
 page.route('https://example.invalid/**',lambda r:(attempts.append(True),r.abort()))
 page.evaluate('''target=>{const e=document.querySelector('ak-flow-executor');e.challenge={component:'xak-flow-redirect',to:target,flowInfo:e.challenge.flowInfo,finalRedirect:true}}''',target)
 a=page.locator('ak-stage-redirect a.pf-m-primary');a.wait_for()
 result=a.evaluate('e=>{const s=getComputedStyle(e);return {bg:s.backgroundColor,color:s.color,height:e.getBoundingClientRect().height,decoration:s.textDecorationLine,arrow:getComputedStyle(e,"::after").content,font:s.fontFamily}}')
 print('Native redirect anchor style:',result)
 assert result['bg']=='rgba(0, 0, 0, 0)' and result['color']=='rgb(21, 34, 60)' and result['height']==43
 assert result['decoration']=='none' and result['arrow']=='"→"' and 'QuietMono' in result['font']
 a.focus();assert a.evaluate('e=>e.getRootNode().activeElement===e')
 a.hover();page.wait_for_timeout(220)
 hover=a.evaluate('e=>getComputedStyle(e).backgroundColor');print('Native anchor hover:',hover)
 assert hover.startswith('rgba(21, 34, 60,') and 0.042<float(hover.rsplit(',',1)[1].rstrip(')'))<0.049
 assert a.evaluate('e=>getComputedStyle(e,"::after").transform')=='matrix(1, 0, 0, 1, 3, 0)'
 page.emulate_media(reduced_motion='reduce');page.wait_for_timeout(80)
 assert a.evaluate('e=>getComputedStyle(e,"::after").transform')=='none'
 assert page.evaluate('document.querySelectorAll("[inert]").length')==0
 a.click();page.wait_for_timeout(300);assert attempts
 assert not errors
 print('PASS: native Follow redirect appearance/hover/reduced-motion/click; anonymous inspector remains denied; zero JS errors')
 b.close()
