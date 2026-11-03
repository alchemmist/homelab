#!/usr/bin/env python3
"""Fresh anonymous trusted-TLS browser acceptance; never enters credentials."""
import asyncio,json,urllib.parse
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  context=await browser.new_context() # trusted TLS, fresh anonymous context
  page=await context.new_page();failures=[];navigation=[]
  page.on('requestfailed',lambda r:failures.append({'url':r.url.split('?')[0],'failure':r.failure}))
  page.on('request',lambda r:navigation.append(urllib.parse.urlsplit(r.url)._replace(query='',fragment='').geturl()) if r.is_navigation_request() else None)
  await page.goto('https://netbird.socrat.alchemmist.xyz/',wait_until='networkidle',timeout=45000)
  await page.wait_for_timeout(5000)
  parts=urllib.parse.urlsplit(page.url)
  assert parts.hostname=='auth.socrat.alchemmist.xyz' and parts.path=='/if/flow/default-authentication-flow/'
  query=urllib.parse.parse_qs(parts.query)
  assert query['redirect_uri']==['https://netbird.socrat.alchemmist.xyz/oauth2/callback']
  assert any('/oauth2/auth' in u for u in navigation)
  inputs=await page.locator('input').evaluate_all('(els)=>els.map(e=>({type:e.type,placeholder:e.placeholder,name:e.name}))')
  links=await page.get_by_role('link').all_text_contents()
  buttons=[s.strip() for s in await page.get_by_role('button').all_text_contents() if s.strip()]
  assert not failures
  assert not any('sign up' in s.lower() or 'register' in s.lower() for s in buttons+links)
  assert any(i['type']=='text' for i in inputs)
  result={'trusted_TLS':True,'fresh_anonymous_context':True,'navigation_without_queries':navigation,'final_host':parts.hostname,'final_path':parts.path,
          'callback_exact':True,'client_id':query['client_id'][0],'buttons':buttons,'links':links,'input_types':[i['type'] for i in inputs],
          'failed_requests':failures,'credentials_entered':False,'personal_owner_login':False}
  print(json.dumps(result,indent=2))
  await browser.close()
if __name__=='__main__':asyncio.run(main())
