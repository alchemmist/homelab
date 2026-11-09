#!/usr/bin/env python3
"""Read-only anonymous native UI checks; no owner HTML, credentials or MFA writes.

The MFA child is a local-only instance of the actual shipped component without
part=challenge. It is never submitted. This is layout acceptance, not real MFA.
The server page is a genuine invalid-client error using login/base_full.html,
the same light-DOM template as Permission denied. Its HTTP 400 is expected.
"""
import argparse
from playwright.sync_api import sync_playwright

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--run', action='store_true')
p.add_argument('--public-edge', choices=['109.173.40.247', '109.120.141.60'], default='109.173.40.247')
a = p.parse_args()
if not a.run:
    p.error('--run required')
BASE = 'https://auth.socrat.alchemmist.xyz'
with sync_playwright() as pw:
    browser = pw.chromium.launch(args=['--host-resolver-rules=MAP auth.socrat.alchemmist.xyz ' + a.public_edge])
    page = browser.new_page(viewport={'width': 1440, 'height': 960})
    errors = []
    page.on('pageerror', lambda e: errors.append(type(e).__name__))
    page.goto(BASE + '/if/flow/default-authentication-flow/')
    page.locator('input[name=uidField]').wait_for()
    for width in [1440, 390]:
        page.set_viewport_size({'width': width, 'height': 960})
        result = page.evaluate('''async () => {
            const host=document.querySelector('ak-flow-executor');
            await customElements.whenDefined('ak-stage-authenticator-validate-code');
            const stage=document.createElement('ak-stage-authenticator-validate-code');
            stage.host=host;
            stage.challenge={component:'ak-stage-authenticator-validate',responseErrors:{},flowInfo:host.challenge.flowInfo};
            stage.deviceChallenge={deviceClass:'totp',deviceUid:'local-layout-only',challenge:{}};
            host.shadowRoot.append(stage);
            try {
                await stage.updateComplete; await new Promise(r=>setTimeout(r,150));
                const button=stage.shadowRoot.querySelector('button[name=continue]');
                const input=stage.shadowRoot.querySelector('input');
                button.focus();const style=getComputedStyle(button);
                return {bg:style.backgroundColor,color:style.color,height:button.getBoundingClientRect().height,
                    arrow:getComputedStyle(button,'::after').content,font:style.fontFamily,
                    focused:stage.shadowRoot.activeElement===button,required:input.required,
                    autocomplete:input.autocomplete,part:stage.getAttribute('part')};
            } finally {stage.remove()}
        }''')
        assert result['bg'] == 'rgba(0, 0, 0, 0)' and result['color'] == 'rgb(21, 34, 60)'
        assert result['height'] == 43 and result['arrow'] == '"→"' and 'QuietMono' in result['font']
        assert result['focused'] and result['required'] and result['autocomplete'] == 'one-time-code'
        assert result['part'] is None
        print('PASS: native nested MFA appearance/focus/validation attributes', width)
    response = page.goto(BASE + '/application/o/authorize/?client_id=quiet-mono-ui-probe&response_type=code')
    assert response.status == 400
    for width in [1440, 390]:
        page.set_viewport_size({'width': width, 'height': 960})
        page.wait_for_timeout(150)
        button = page.locator('#ak-back-home')
        result = button.evaluate('''e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,
            height:e.getBoundingClientRect().height,arrow:getComputedStyle(e,'::after').content})''')
        assert result['height'] == 43 and result['bg'] == 'rgba(0, 0, 0, 0)'
        assert result['color'] == 'rgb(21, 34, 60)' and result['arrow'] == '"→"'
        card = page.locator('.pf-c-login__main').bounding_box()
        assert abs(card['x'] + card['width']/2 - width/2) < 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        button.focus()
        assert button.evaluate('e=>document.activeElement===e')
        page.emulate_media(reduced_motion='reduce')
        button.hover()
        assert button.evaluate('e=>getComputedStyle(e,"::after").transform') == 'none'
        print('PASS: real server error shared denial template, centered/mobile/focus/reduced motion', width)
    assert not errors
    browser.close()
