#!/usr/bin/env python3

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pyjs.tooling import stop_process
from pyjs.tooling.browser import Browser, free_port, wait_for_http

PROJECT_ROOT = Path.cwd()
OUTPUT = PROJECT_ROOT / "screenshots"


async def exercise() -> dict:
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    environment = os.environ.copy()
    environment["PYJS_PORT"] = str(port)
    with tempfile.TemporaryFile(mode="w+") as server_log:
        server = subprocess.Popen(
            [sys.executable, "-m", "pyjs_examples.store"],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        try:
            await wait_for_http(url, timeout=20)
            async with Browser() as browser:
                page = await browser.new_page(url)
                await page.set_viewport(1440, 1000)
                await page.wait_for(
                    "customElements.get('catalog-page') !== undefined",
                    "the hydrated storefront",
                )
                OUTPUT.mkdir(parents=True, exist_ok=True)
                await page.screenshot(OUTPUT / "store-home.png")
                await page.click(
                    '[data-product-card="Canvas field bag"] '
                    "[data-product-details]"
                )
                await page.wait_for_text(
                    '[data-testid="product-insights"]',
                    "Pairs well with",
                    "the product recommendations",
                )
                await page.screenshot(
                    OUTPUT / "store-insights.png",
                    selector="[data-product-insights]",
                )
                await page.fill(
                    '[data-testid="catalog-sort"]',
                    "price-descending",
                )
                await page.wait_for_selector(
                    '[data-product-card="Task lamp"]',
                    "the sorted catalog",
                )
                await page.screenshot(OUTPUT / "store-sorted.png")
                await page.click('[data-product="Task lamp"]')
                await page.fill('[data-testid="catalog-sort"]', "featured")
                await page.wait_for_selector(
                    '[data-product-card="Daily notebook"]',
                    "the featured catalog",
                )
                await page.click('[data-product="Daily notebook"]')
                await page.click('[data-testid="cart-trigger"]')
                await page.wait_for_text(
                    '[data-slot="sheet-content"]',
                    "$172",
                    "the cart subtotal",
                )
                await page.screenshot(OUTPUT / "store-cart.png")
                cart_items = await page.attributes(
                    "[data-cart-item]", "data-cart-item"
                )
                subtotal = await page.text('[data-slot="sheet-content"]')
                await page.navigate(url + "account/reviews/")
                await page.wait_for(
                    "document.querySelector('review-moderation-page')"
                    "?._initialized === true",
                    "the review moderation page",
                )
                await page.screenshot(OUTPUT / "store-review-moderation.png")
                moderation = await page.text(
                    '[data-testid="review-moderation-rows"]'
                )
                await page.navigate(url + "account/visitors/")
                await page.wait_for(
                    "document.querySelector('visitor-activity-page')"
                    "?._initialized === true",
                    "the visitor activity page",
                )
                await page.screenshot(OUTPUT / "store-visitor-activity.png")
                result = {
                    "cartItems": cart_items,
                    "subtotal": subtotal,
                    "moderation": moderation,
                    "visitorEvents": await page.evaluate(
                        "document.querySelectorAll('[data-visitor-event]').length"
                    ),
                    "errors": page.exceptions,
                }
                if result["errors"]:
                    raise RuntimeError("Browser errors: " + "; ".join(result["errors"]))
                (OUTPUT / "store.json").write_text(
                    json.dumps(result, indent=2) + "\n",
                    encoding="utf-8",
                )
                return result
        except BaseException:
            stop_process(server)
            server_log.seek(0)
            sys.stderr.write(server_log.read())
            raise
        finally:
            stop_process(server)


async def main() -> None:
    print(json.dumps(await exercise(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
