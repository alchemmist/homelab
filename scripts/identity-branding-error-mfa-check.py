#!/usr/bin/env python3
"""Read-only anonymous native UI checks; no owner HTML, credentials or MFA writes.

The MFA child is a local-only instance of the actual shipped component without
part=challenge. It is never submitted. This is layout acceptance, not real MFA.
The server page is a genuine invalid-client error using login/base_full.html,
the same light-DOM template as Permission denied. Its HTTP 400 is expected.
"""

import argparse

from playwright.sync_api import sync_playwright

BUTTON_HEIGHT_PX = 43
HTTP_CLIENT_ERROR = 400

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--run", action="store_true")
p.add_argument(
    "--public-edge",
    choices=["109.173.40.247", "109.120.141.60"],
    default="109.173.40.247",
)
a = p.parse_args()
if not a.run:
    p.error("--run required")
BASE = "https://auth.socrat.alchemmist.xyz"
with sync_playwright() as pw:
    browser = pw.chromium.launch(
        args=["--host-resolver-rules=MAP auth.socrat.alchemmist.xyz " + a.public_edge]
    )
    page = browser.new_page(viewport={"width": 1440, "height": 960})
    errors = []
    page.on("pageerror", lambda e: errors.append(type(e).__name__))
    page.goto(BASE + "/if/flow/default-authentication-flow/")
    page.locator("input[name=uidField]").wait_for()
    for width in [1440, 390]:
        page.set_viewport_size({"width": width, "height": 960})
        result = page.evaluate("""async () => {
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
                const rect=button.getBoundingClientRect();
                return {bg:style.backgroundColor,color:style.color,height:rect.height,
                    arrow:getComputedStyle(button,'::after').content,font:style.fontFamily,
                    focused:stage.shadowRoot.activeElement===button,required:input.required,
                    autocomplete:input.autocomplete,part:stage.getAttribute('part')};
            } finally {stage.remove()}
        }""")
        if result["bg"] != "rgba(0, 0, 0, 0)":
            msg = "Continue button background must stay transparent"
            raise RuntimeError(msg)
        if result["color"] != "rgb(21, 34, 60)":
            msg = "Continue button must keep the reviewed ink color"
            raise RuntimeError(msg)
        if result["height"] != BUTTON_HEIGHT_PX:
            msg = "Continue button must stay 43px tall"
            raise RuntimeError(msg)
        if result["arrow"] != '"→"':
            msg = "Continue button must keep the reviewed arrow glyph"
            raise RuntimeError(msg)
        if "QuietMono" not in result["font"]:
            msg = "Continue button must use the reviewed QuietMono face"
            raise RuntimeError(msg)
        if not result["focused"]:
            msg = "Continue button must self-focus"
            raise RuntimeError(msg)
        if not result["required"]:
            msg = "Code input must stay required"
            raise RuntimeError(msg)
        if result["autocomplete"] != "one-time-code":
            msg = "Code input must keep the one-time-code autocomplete token"
            raise RuntimeError(msg)
        if result["part"] is not None:
            msg = "Nested stage must stay unparted"
            raise RuntimeError(msg)
        print("PASS: native nested MFA appearance/focus/validation attributes", width)
    response = page.goto(
        BASE + "/application/o/authorize/?client_id=quiet-mono-ui-probe&response_type=code"
    )
    assert_status = response.status if response else None
    if assert_status != HTTP_CLIENT_ERROR:
        msg = "Invalid-client request must produce HTTP 400"
        raise RuntimeError(msg)
    for width in [1440, 390]:
        page.set_viewport_size({"width": width, "height": 960})
        page.wait_for_timeout(150)
        button = page.locator("#ak-back-home")
        result = button.evaluate(
            """e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,
            height:e.getBoundingClientRect().height,arrow:getComputedStyle(e,'::after').content})"""
        )
        if result["height"] != BUTTON_HEIGHT_PX:
            msg = "Back-home button must stay 43px tall"
            raise RuntimeError(msg)
        if result["bg"] != "rgba(0, 0, 0, 0)":
            msg = "Back-home button background must stay transparent"
            raise RuntimeError(msg)
        if result["color"] != "rgb(21, 34, 60)":
            msg = "Back-home button must keep the reviewed ink color"
            raise RuntimeError(msg)
        if result["arrow"] != '"→"':
            msg = "Back-home button must keep the reviewed arrow glyph"
            raise RuntimeError(msg)
        card = page.locator(".pf-c-login__main").bounding_box()
        if card is None:
            msg = "Login card must exist on the denial page"
            raise RuntimeError(msg)
        if abs(card["x"] + card["width"] / 2 - width / 2) >= 1:
            msg = "Login card must stay horizontally centered"
            raise RuntimeError(msg)
        if not page.evaluate("document.documentElement.scrollWidth <= innerWidth"):
            msg = "Denial page must not overflow the viewport"
            raise RuntimeError(msg)
        button.focus()
        if not button.evaluate("e=>document.activeElement===e"):
            msg = "Back-home button must self-focus"
            raise RuntimeError(msg)
        page.emulate_media(reduced_motion="reduce")
        button.hover()
        if button.evaluate('e=>getComputedStyle(e,"::after").transform') != "none":
            msg = "Reduced motion must disable the arrow transition"
            raise RuntimeError(msg)
        print(
            "PASS: real server error shared denial template, centered/mobile/focus/reduced motion",
            width,
        )
    if errors:
        msg = "Browser reported page errors: " + ", ".join(errors)
        raise RuntimeError(msg)
    browser.close()
