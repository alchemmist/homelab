#!/usr/bin/env python3
"""Anonymous, read-only Nature performance/branding checks. No login/owner factors.

No screenshots, private HTML, traces or cookies are persisted. --run required.
"""

import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", action="store_true")
parser.add_argument(
    "--delay-hq",
    action="store_true",
    help="Also hold HQ locally for 5s to verify usable preview-only login",
)
parser.add_argument("--public-edge", choices=["109.173.40.247", "109.120.141.60"])
args = parser.parse_args()
if not args.run:
    parser.error("--run required")
import hashlib
import json
from pathlib import Path
from typing import cast

from playwright.sync_api import Page, Response, Route, sync_playwright

root = Path(__file__).resolve().parents[1] / "deploy/authentik/quiet-mono"
assets = json.loads((root / "assets.json").read_text())
photos = json.loads((root / "nature.json").read_text())["photos"]
css_hashes = {assets[p["sceneCss"]]["sha256"] for p in photos}
BASE = "https://auth.socrat.alchemmist.xyz"
with sync_playwright() as p:
    for edge in [args.public_edge] if args.public_edge else ["109.173.40.247", "109.120.141.60"]:
        browser = p.chromium.launch(
            args=["--host-resolver-rules=MAP auth.socrat.alchemmist.xyz " + edge]
        )
        for width, height, variant in [(1440, 960, "desktop"), (390, 844, "mobile")]:
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            responses: list[Response] = []
            errors: list[bool] = []
            page.on(
                "response",
                lambda r, responses=responses: (
                    responses.append(r) if "/-/quiet-mono/v1/" in r.url else None
                ),
            )
            page.on("pageerror", lambda _e, errors=errors: errors.append(True))
            page.goto(BASE + "/if/flow/default-authentication-flow/")
            page.locator("input[name=uidField]").wait_for()
            page.wait_for_timeout(600)
            scenes = [r for r in responses if r.url.endswith("/nature/scene.css")]
            if len(scenes) != 1:
                msg = "One journey CSS response per document"
                raise RuntimeError(msg)
            scene = scenes[0]
            if scene.status != 200:
                msg = "Journey scene CSS response must be HTTP 200"
                raise RuntimeError(msg)
            if scene.headers["cache-control"] != "no-store":
                msg = "Journey scene CSS must be served no-store"
                raise RuntimeError(msg)
            if hashlib.sha256(scene.body()).hexdigest() not in css_hashes:
                msg = "Scene CSS body hash must match the pinned assets manifest"
                raise RuntimeError(msg)
            photo = next(p for p in photos if p["id"] == scene.headers["x-quiet-mono-scene"])
            key = photo[variant + "Avif"]
            item = assets[key]
            image = next(r for r in responses if r.url.endswith("-" + Path(item["path"]).name))
            if image.status != 200:
                msg = "Chosen photograph response must be HTTP 200"
                raise RuntimeError(msg)
            if image.headers["content-type"] != "image/avif":
                msg = "Chosen photograph must be served as AVIF"
                raise RuntimeError(msg)
            if "immutable" not in image.headers["cache-control"]:
                msg = "Chosen photograph must be cache immutable"
                raise RuntimeError(msg)
            if hashlib.sha256(image.body()).hexdigest() != item["sha256"]:
                msg = "Photograph body hash must match the pinned assets manifest"
                raise RuntimeError(msg)
            full = [
                r for r in responses if r.url.endswith((".avif", ".webp")) and "-nature-" in r.url
            ]
            if len(full) != 1:
                msg = "Only one full-size photograph; no desktop download on mobile"
                raise RuntimeError(msg)
            style = page.evaluate("getComputedStyle(document.body,'::before').backgroundImage")
            if "data:image/webp;base64," not in style:
                msg_0 = "Body background must embed the same photograph as WebP data URI"
                raise RuntimeError(msg_0)
            if Path(item["path"]).name not in style:
                msg = "Inline background must be the pinned same-photo image"
                raise RuntimeError(msg)
            if (
                page.locator("ak-drawer#flow-drawer").evaluate(
                    "e=>getComputedStyle(e).backgroundImage"
                )
                != "none"
            ):
                msg = "Flow drawer must stay unstyled during the journey"
                raise RuntimeError(msg)
            timing = page.evaluate(
                "performance.getEntriesByType('resource').filter(x=>x.name.endsWith('.avif')).map(x=>({start:Math.round(x.startTime),end:Math.round(x.responseEnd),bytes:x.transferSize}))[0]"
            )
            # Re-request the already chosen immutable image using the browser HTTP cache.
            page.evaluate(
                "async url=>{await(await fetch(url,"
                "{mode:'no-cors',credentials:'include'})).arrayBuffer()}",
                image.url,
            )
            cached = page.evaluate(
                "url=>performance.getEntriesByName(url).at(-1).transferSize", image.url
            )
            if cached != 0:
                msg = "Previously selected image must reuse browser cache"
                raise RuntimeError(msg)
            count = len(responses)
            page.wait_for_timeout(1200)
            if len(responses) != count:
                msg = "No slideshow/background rotation"
                raise RuntimeError(msg)
            if errors:
                msg = "Page errors must be empty during the journey"
                raise RuntimeError(msg)
            print(
                "PASS",
                edge,
                variant,
                "one scene CSS + one AVIF; same-photo inline preview; warm image transfer 0 bytes;",
                timing,
                flush=True,
            )
            # Real full-document transitions, not just fetching the CSS endpoint.
            # Use synthetic local test state; never submit a password or MFA challenge.
            journey = (
                BASE
                + "/if/flow/default-authentication-flow/"
                + "?next=%2Fapplication%2Fo%2Fauthorize%2F"
                + "%3Fclient_id%3Dlayout-only%26state%3Dread-only-journey"
            )

            def current_scene(page: Page = page) -> str:
                """Perform the current scene operation."""
                page.wait_for_function(
                    "getComputedStyle(document.body,'::before').getPropertyValue('--qm-scene').trim().length===12"
                )
                return cast(
                    "str",
                    page.evaluate(
                        "getComputedStyle(document.body,'::before').getPropertyValue('--qm-scene').trim()"
                    ),
                )

            page.goto(journey)
            page.locator("input[name=uidField]").wait_for()
            chosen = current_scene()
            for _attempt in range(3):
                page.reload()
                page.locator("input[name=uidField]").wait_for()
                if current_scene() != chosen:
                    msg = "Scene must not rotate across native login reloads"
                    raise RuntimeError(msg)
            error = page.goto(
                BASE
                + "/application/o/authorize/?client_id=quiet-mono-layout-probe&response_type=code"
            )
            if error.status != 400:
                msg = "Read-only authorize probe must be rejected with HTTP 400"
                raise RuntimeError(msg)
            if current_scene() != chosen:
                msg = "Server-rendered error page must reuse the first journey seed"
                raise RuntimeError(msg)
            page.goto(journey)
            page.locator("input[name=uidField]").wait_for()
            if current_scene() != chosen:
                msg = "Return to the login must reuse the first journey seed"
                raise RuntimeError(msg)
            # Independent concurrent OIDC journeys must not replace the first one's seed.
            other = context.new_page()
            other.goto(journey + "-other")
            other.locator("input[name=uidField]").wait_for()
            page.reload()
            page.locator("input[name=uidField]").wait_for()
            if current_scene() != chosen:
                msg = "A concurrent journey must not rotate the first flow seed"
                raise RuntimeError(msg)
            other.close()
            print(
                "PASS",
                edge,
                variant,
                "native login reload x3 -> native server error -> login; "
                "concurrent journey does not rotate first flow",
                flush=True,
            )
            context.close()
        context = browser.new_context()
        page = context.new_page()
        scene_ids: set[str] = set()
        for _ in range(12):
            r = page.goto(BASE + "/-/quiet-mono/v1/nature/scene.css")
            if r.status != 200:
                msg = "Working-session scene CSS must be HTTP 200"
                raise RuntimeError(msg)
            if hashlib.sha256(r.body()).hexdigest() not in css_hashes:
                msg = "Working-session CSS hash must match the pinned manifest"
                raise RuntimeError(msg)
            scene_ids.add(r.headers["x-quiet-mono-scene"])
        if len(scene_ids) != 1:
            msg = "Repeated CSS requests must not rotate a working-session background"
            raise RuntimeError(msg)
        chosen = next(iter(scene_ids))
        cookie = next(
            c
            for c in context.cookies(BASE + "/-/quiet-mono/v1/nature/scene.css")
            if c["name"] == "__Secure-qm_nature"
        )
        if cookie["value"] != chosen:
            msg = "Session cookie must pin the served scene id"
            raise RuntimeError(msg)
        if not cookie["secure"]:
            msg = "Session cookie must be Secure"
            raise RuntimeError(msg)
        if not cookie["httpOnly"]:
            msg = "Session cookie must be HttpOnly"
            raise RuntimeError(msg)
        if cookie["sameSite"] != "Lax":
            msg = "Session cookie must be SameSite=Lax"
            raise RuntimeError(msg)
        if cookie["path"] != "/-/quiet-mono/v1/":
            msg = "Session cookie must be scoped to the quiet-mono mount"
            raise RuntimeError(msg)
        for i in range(12):
            # Synthetic public test identifiers, not real callback/session artifacts.
            ref = (
                BASE
                + "/if/flow/default-authentication-flow/"
                + "?next=%2Fapplication%2Fo%2Fauthorize%2F"
                + "%3Fclient_id%3Dlayout-only%26state%3Djourney-"
                + str(i)
            )
            r = context.request.get(
                BASE + "/-/quiet-mono/v1/nature/scene.css", headers={"Referer": ref}
            )
            scene = r.headers["x-quiet-mono-scene"]
            scene_ids.add(scene)
            for slug in [
                "default-authentication-flow",
                "default-provider-authorization-implicit-consent",
            ]:
                repeated = context.request.get(
                    BASE + "/-/quiet-mono/v1/nature/scene.css",
                    headers={"Referer": ref.replace("default-authentication-flow", slug)},
                )
                if repeated.headers["x-quiet-mono-scene"] != scene:
                    msg_0 = "Repeated request within one journey must keep its sampled scene"
                    raise RuntimeError(msg_0)
            fallback = context.request.get(BASE + "/-/quiet-mono/v1/nature/scene.css")
            if fallback.headers["x-quiet-mono-scene"] != scene:
                msg = "Referer-less fallback must keep the working journey scene"
                raise RuntimeError(msg)
        if not (len(scene_ids) >= 4):
            msg = "New OIDC journeys resample the full collection"
            raise RuntimeError(msg)
        for path in ["scene.css", "desktop", "mobile"]:
            if context.request.post(BASE + "/-/quiet-mono/v1/nature/" + path).status != 403:
                msg = "Scene or fallback POST must be denied with HTTP 403"
                raise RuntimeError(msg)
        # Backward-compatible non-AVIF native clients receive the original pinned WebP.
        r = context.request.get(
            BASE + "/-/quiet-mono/v1/nature/mobile",
            headers={"Accept": "image/webp"},
            max_redirects=0,
        )
        if r.status != 302:
            msg = "Non-AVIF fallback must redirect to pinned WebP"
            raise RuntimeError(msg)
        if r.headers["cache-control"] != "no-store":
            msg = "Fallback redirect must be served no-store"
            raise RuntimeError(msg)
        fallback = context.request.get(BASE + r.headers["location"])
        if fallback.status != 200:
            msg = "Fallback WebP must be HTTP 200"
            raise RuntimeError(msg)
        if fallback.headers["content-type"] != "image/webp":
            msg = "Fallback must be served as WebP"
            raise RuntimeError(msg)
        if hashlib.sha256(fallback.body()).hexdigest() not in {
            assets[p["mobile"]]["sha256"] for p in photos
        }:
            msg = "Fallback WebP hash must match a pinned mobile asset"
            raise RuntimeError(msg)
        print(
            "PASS",
            edge,
            "stable journeys; new-journey choices:",
            len(scene_ids),
            "/12; scoped cookie; POST denied; pinned WebP fallback",
            flush=True,
        )
        context.close()
        browser.close()


if args.delay_hq:
    import asyncio

    from playwright.async_api import async_playwright

    async def preview_only() -> None:
        """Perform the preview only operation."""
        async with async_playwright() as p:
            for edge in (
                [args.public_edge] if args.public_edge else ["109.173.40.247", "109.120.141.60"]
            ):
                browser = await p.chromium.launch(
                    args=["--host-resolver-rules=MAP auth.socrat.alchemmist.xyz " + edge]
                )
                for width in [1440, 390]:
                    page = await browser.new_page(viewport={"width": width, "height": 960})
                    release = asyncio.Event()
                    pending: list[bool] = []

                    async def hold(
                        route: Route,
                        pending: list[bool] = pending,
                        release: asyncio.Event = release,
                    ) -> None:
                        pending.append(True)
                        await release.wait()
                        await route.continue_()

                    await page.route("**/*-nature-*.avif", hold)
                    try:
                        await page.goto(
                            BASE + "/if/flow/default-authentication-flow/",
                            wait_until="domcontentloaded",
                        )
                        await page.locator("input[name=uidField]").wait_for()
                        if not pending:
                            msg = "HQ hold route must stall the AVIF request"
                            raise RuntimeError(msg)
                        if release.is_set():
                            msg_0 = "HQ preview must not release while the login form loads"
                            raise RuntimeError(msg_0)
                        if not (await page.locator("input[name=uidField]").is_enabled()):
                            msg_0 = "Preview-only native login must be usable while HQ is held"
                            raise RuntimeError(msg_0)
                        if "data:image/webp;base64," not in (
                            await page.evaluate(
                                "getComputedStyle(document.body,'::before').backgroundImage"
                            )
                        ):
                            msg_0 = "Preview background must embed the same WebP photograph"
                            raise RuntimeError(msg_0)
                        await page.wait_for_timeout(5000)
                        if not (await page.locator("input[name=uidField]").is_enabled()):
                            msg_0 = "Native login must stay usable for the full 5s HQ hold"
                            raise RuntimeError(msg_0)
                        print(
                            "PASS preview-only native login usable with HQ held for 5s",
                            edge,
                            width,
                            flush=True,
                        )
                    finally:
                        release.set()
                        await page.wait_for_timeout(500)
                        await page.close()
                await browser.close()

    asyncio.run(preview_only())
