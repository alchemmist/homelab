#!/usr/bin/env python3
"""Read-only live CSS/native-component probes, not owner-session acceptance.

Fresh anonymous browser only. The inspector query exposes a native debug toggle,
but its API must remain denied. The redirect challenge is a local browser-only
layout probe with a blocked .invalid target, not a server auth response. No real
saved HTML, session/context, credentials, screenshots or fixtures are stored.
"""

import argparse

from playwright.sync_api import Route, sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", action="store_true")
parser.add_argument(
    "--public-edge",
    choices=["109.173.40.247", "109.120.141.60"],
    default="109.173.40.247",
)
args = parser.parse_args()
if not args.run:
    parser.error("--run is required for live read-only UI probes")
BASE = "https://auth.socrat.alchemmist.xyz"

TARGET_PX = 39
ICON_PX = 18
HISTORY_HEIGHT_PX = 1000
ANCHOR_HEIGHT_PX = 43
HOVER_ALPHA_MIN = 0.042
HOVER_ALPHA_MAX = 0.049
with sync_playwright() as p:
    b = p.chromium.launch(
        args=["--host-resolver-rules=MAP auth.socrat.alchemmist.xyz " + args.public_edge]
    )
    page = b.new_page(viewport={"width": 1440, "height": 960})
    errors = []
    statuses = []
    page.on("pageerror", lambda e: errors.append(type(e).__name__))
    page.on(
        "response",
        lambda r: statuses.append(r.status) if "/flows/inspector/" in r.url else None,
    )
    page.goto(BASE + "/if/flow/default-authentication-flow/?inspector=available")
    page.locator("input[name=uidField]").wait_for()
    # Normal anonymous login must not show the debug control without its explicit query.
    anonymous = b.new_page()
    anonymous.goto(BASE + "/if/flow/default-authentication-flow/")
    anonymous.locator("input[name=uidField]").wait_for()
    if anonymous.get_by_role("button", name="Open flow inspector", exact=True).count() != 0:
        msg = "Anonymous login must not expose the inspector toggle"
        raise RuntimeError(msg)
    anonymous.close()
    toggle = page.get_by_role("button", name="Open flow inspector", exact=True)
    toggle.wait_for()
    for width, offset in [(1440, 24), (390, 17)]:
        page.set_viewport_size({"width": width, "height": 960})
        page.wait_for_timeout(250)
        box = toggle.bounding_box()
        if not (abs(box["y"] - offset) < 1):
            msg = "Inspector toggle must sit at the reviewed vertical offset"
            raise RuntimeError(msg)
        if not (abs(width - box["x"] - box["width"] - offset) < 1):
            msg = "Inspector toggle must sit at the reviewed horizontal offset"
            raise RuntimeError(msg)
        if box["width"] != TARGET_PX or box["height"] != TARGET_PX:
            msg = "Inspector hit target must be a reviewed square"
            raise RuntimeError(msg)
        icon = page.locator("ak-flow-inspector-button i")
        ic = icon.bounding_box()
        if ic["width"] != ICON_PX or ic["height"] != ICON_PX:
            msg = "Inspector icon must be the reviewed square glyph"
            raise RuntimeError(msg)
        if not (abs(ic["x"] + 9 - box["x"] - 19.5) < 1):
            msg = "Inspector icon must be horizontally centered"
            raise RuntimeError(msg)
        if not (abs(ic["y"] + 9 - box["y"] - 19.5) < 1):
            msg = "Inspector icon must be vertically centered"
            raise RuntimeError(msg)
        if "data:image/svg+xml" not in icon.evaluate("e=>getComputedStyle(e).maskImage"):
            msg = "Inspector icon must render via the reviewed SVG mask"
            raise RuntimeError(msg)
        print(
            "PASS: actual native magnifier, square hit target, "
            "centered 18px icon and viewport offset",
            width,
        )
    page.set_viewport_size({"width": 1440, "height": 960})
    toggle.click()
    page.wait_for_timeout(1000)
    if not statuses:
        msg = "Inspector session must have produced responses"
        raise RuntimeError(msg)
    if statuses[-1] not in (403, 404):
        msg = "Native inspector API must remain denied"
        raise RuntimeError(msg)
    # Empty local layout box only: no native snapshots/history entries are forged.
    for width in [1440, 390]:
        page.set_viewport_size({"width": width, "height": 960})
        result = page.locator("ak-flow-inspector").evaluate("""e=>{
   const box=document.createElement('ol');box.className='pf-c-progress-stepper';
   box.style.height='1000px';
   e.shadowRoot.append(box);
   try{const s=getComputedStyle(box);return {max:s.maxBlockSize,overflow:s.overflowY,
   height:box.getBoundingClientRect().height}}
   finally{box.remove()}
  }""")
        if result["max"] != "none":
            msg = "Plan History must allow natural block height"
            raise RuntimeError(msg)
        if result["overflow"] != "visible":
            msg = "Plan History must not scroll internally"
            raise RuntimeError(msg)
        if result["height"] != HISTORY_HEIGHT_PX:
            msg = "Plan History box must keep its probed height"
            raise RuntimeError(msg)
        print("PASS: Plan History natural height, no internal scrolling", width)
    page.set_viewport_size({"width": 1440, "height": 960})
    # Local-only native component probe, not an authentication response or permission grant.
    target = "https://example.invalid/quiet-mono-native-control-probe"
    attempts: list[bool] = []

    def block_route(route: Route) -> None:
        """Record the attempt and abort the blocked local probe route."""
        attempts.append(True)
        route.abort()

    page.route("https://example.invalid/**", block_route)
    page.evaluate(
        """target=>{const e=document.querySelector('ak-flow-executor');
        e.challenge={component:'xak-flow-redirect',to:target,
        flowInfo:e.challenge.flowInfo,finalRedirect:true}}""",
        target,
    )
    a = page.locator("ak-stage-redirect a.pf-m-primary")
    a.wait_for()
    result = a.evaluate(
        "e=>{const s=getComputedStyle(e);return {bg:s.backgroundColor,color:s.color,"
        "height:e.getBoundingClientRect().height,decoration:s.textDecorationLine,"
        'arrow:getComputedStyle(e,"::after").content,font:s.fontFamily}}'
    )
    print("Native redirect anchor style:", result)
    if result["bg"] != "rgba(0, 0, 0, 0)":
        msg = "Native Follow anchor must have a transparent background"
        raise RuntimeError(msg)
    if result["color"] != "rgb(21, 34, 60)":
        msg = "Native Follow anchor must use the ink color"
        raise RuntimeError(msg)
    if result["height"] != ANCHOR_HEIGHT_PX:
        msg = "Native Follow anchor must keep the reviewed height"
        raise RuntimeError(msg)
    if result["decoration"] != "none":
        msg = "Native Follow anchor must not underline"
        raise RuntimeError(msg)
    if result["arrow"] != '"→"':
        msg = "Native Follow anchor must keep its arrow glyph"
        raise RuntimeError(msg)
    if "QuietMono" not in result["font"]:
        msg = "Native Follow anchor must use the QuietMono typeface"
        raise RuntimeError(msg)
    a.focus()
    if not a.evaluate("e=>e.getRootNode().activeElement===e"):
        msg = "Native Follow anchor must be the active element on focus"
        raise RuntimeError(msg)
    a.hover()
    page.wait_for_timeout(220)
    hover = a.evaluate("e=>getComputedStyle(e).backgroundColor")
    print("Native anchor hover:", hover)
    if not hover.startswith("rgba(21, 34, 60,"):
        msg = "Native Follow hover must use the ink overlay"
        raise RuntimeError(msg)
    hover_alpha = float(hover.rsplit(",", 1)[1].rstrip(")"))
    if not HOVER_ALPHA_MIN < hover_alpha < HOVER_ALPHA_MAX:
        msg = "Native Follow hover alpha must stay within the reviewed range"
        raise RuntimeError(msg)
    if a.evaluate('e=>getComputedStyle(e,"::after").transform') != "matrix(1, 0, 0, 1, 3, 0)":
        msg = "Native Follow arrow must keep its reviewed transform"
        raise RuntimeError(msg)
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_timeout(80)
    if a.evaluate('e=>getComputedStyle(e,"::after").transform') != "none":
        msg = "Reduced motion must remove the arrow transform"
        raise RuntimeError(msg)
    if page.evaluate('document.querySelectorAll("[inert]").length') != 0:
        msg = "No element may be left inert after the native probes"
        raise RuntimeError(msg)
    a.click()
    page.wait_for_timeout(300)
    if not attempts:
        msg = "Follow redirect click must hit the blocked local probe route"
        raise RuntimeError(msg)
    if errors:
        msg = "The live branding probes must run without page errors"
        raise RuntimeError(msg)
    print(
        "PASS: native Follow redirect appearance/hover/reduced-motion/click; "
        "anonymous inspector remains denied; zero JS errors"
    )
    b.close()
