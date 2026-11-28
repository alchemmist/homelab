#!/usr/bin/env python3
"""Fresh anonymous trusted-TLS browser acceptance; never enters credentials."""

import asyncio
import json
import urllib.parse

from playwright.async_api import async_playwright


async def main() -> None:
    """Verify the public NetBird entry redirects to the reviewed auth flow."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()  # trusted TLS, fresh anonymous context
        page = await context.new_page()
        failures: list[object] = []
        navigation: list[str] = []
        page.on(
            "requestfailed",
            lambda r: failures.append({"url": r.url.split("?")[0], "failure": r.failure}),
        )
        page.on(
            "request",
            lambda r: (
                navigation.append(
                    urllib.parse.urlsplit(r.url)._replace(query="", fragment="").geturl()
                )
                if r.is_navigation_request()
                else None
            ),
        )
        await page.goto(
            "https://netbird.socrat.alchemmist.xyz/",
            wait_until="networkidle",
            timeout=45000,
        )
        await page.wait_for_timeout(5000)
        parts = urllib.parse.urlsplit(page.url)
        if parts.hostname != "auth.socrat.alchemmist.xyz":
            msg = "Entry redirected to an unreviewed host"
            raise RuntimeError(msg)
        if parts.path != "/if/flow/default-authentication-flow/":
            msg = "Entry redirected to an unreviewed auth flow"
            raise RuntimeError(msg)
        query = urllib.parse.parse_qs(parts.query)
        if query["redirect_uri"] != ["https://netbird.socrat.alchemmist.xyz/oauth2/callback"]:
            msg = "Entry redirected with an unreviewed callback"
            raise RuntimeError(msg)
        if not any("/oauth2/auth" in u for u in navigation):
            msg = "OAuth2 authorization step missing from the navigation"
            raise RuntimeError(msg)
        inputs = await page.locator("input").evaluate_all(
            "(els)=>els.map(e=>({type:e.type,placeholder:e.placeholder,name:e.name}))"
        )
        links = await page.get_by_role("link").all_text_contents()
        buttons = [
            s.strip() for s in await page.get_by_role("button").all_text_contents() if s.strip()
        ]
        if failures:
            msg = "Public entry produced failed requests"
            raise RuntimeError(msg)
        if any("sign up" in s.lower() or "register" in s.lower() for s in buttons + links):
            msg = "Sign-up affordances exposed on the public entry"
            raise RuntimeError(msg)
        if not any(i["type"] == "text" for i in inputs):
            msg = "Expected credential input missing from the auth flow"
            raise RuntimeError(msg)
        result = {
            "trusted_TLS": True,
            "fresh_anonymous_context": True,
            "navigation_without_queries": navigation,
            "final_host": parts.hostname,
            "final_path": parts.path,
            "callback_exact": True,
            "client_id": query["client_id"][0],
            "buttons": buttons,
            "links": links,
            "input_types": [i["type"] for i in inputs],
            "failed_requests": failures,
            "credentials_entered": False,
            "personal_owner_login": False,
        }
        print(json.dumps(result, indent=2))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
