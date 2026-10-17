import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from pyjs.tooling import stop_process
from pyjs.tooling.browser import Browser, free_port, wait_for_http

TEST_STATIC_ROOT = Path(tempfile.gettempdir()) / f"pyjs-store-browser-{os.getpid()}"


@pytest.fixture(scope="module", autouse=True)
def shared_store_build():
    shutil.rmtree(TEST_STATIC_ROOT, ignore_errors=True)
    yield
    shutil.rmtree(TEST_STATIC_ROOT, ignore_errors=True)


@asynccontextmanager
async def running_store():
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    environment = os.environ.copy()
    environment["PYJS_PORT"] = str(port)
    environment["PYJS_STORE_TEST_STATIC_ROOT"] = str(TEST_STATIC_ROOT)
    environment["PYTHONUNBUFFERED"] = "1"
    server = subprocess.Popen(
        [sys.executable, "-m", "pyjs_examples.store"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        await wait_for_http(url, timeout=120)
        yield url
    finally:
        stop_process(server)


def test_store_checkout_updates_an_observing_catalog():
    async def run():
        async with running_store() as url:
            async with Browser() as browser:
                shopper = await browser.new_page(url)
                await shopper.wait_for_selector("catalog-page")
                await shopper.wait_for(
                    "document.querySelector('catalog-page')._initialized === true",
                    "the store to hydrate",
                )
                assert shopper.exceptions == []
                await shopper.wait_for(
                    "document.querySelector('catalog-page')"
                    ".live_session?.transport === 'sse'",
                    "the live catalog to connect",
                )
                observer = await browser.new_page(url)
                await observer.wait_for_selector("catalog-page")
                await observer.wait_for(
                    "document.querySelector('catalog-page')._initialized === true",
                    "the observing store to hydrate",
                )
                assert observer.exceptions == []
                await observer.wait_for(
                    "document.querySelector('catalog-page')"
                    ".live_session?.transport === 'sse'",
                    "the observing live catalog to connect",
                )

                await shopper.wait_for_text(
                    '[data-testid="catalog-search-status"]',
                    "2 of 4 products",
                )
                await shopper.wait_for_count("[data-product-card]", 2)
                assert await shopper.attribute(
                    '[data-testid="catalog-previous"]', "disabled"
                ) == ""
                await shopper.click(
                    '[data-product-card="Canvas field bag"] '
                    "[data-product-details]"
                )
                await shopper.wait_for_text(
                    '[data-testid="product-insights"]',
                    "Noah",
                )
                await shopper.wait_for_text(
                    '[data-testid="product-insights"]',
                    "Task lamp",
                )
                assert await shopper.attribute(
                    "[data-product-insights]",
                    "data-product-insights",
                ) == "Canvas field bag"
                await shopper.click('[data-testid="catalog-next"]')
                await shopper.wait_for_selector(
                    '[data-product-card="Task lamp"]',
                    "the next catalog page",
                )
                await shopper.wait_for_count("[data-product-card]", 2)
                assert await shopper.attribute(
                    '[data-testid="catalog-next"]', "disabled"
                ) == ""
                await shopper.click('[data-testid="catalog-previous"]')
                await shopper.wait_for_selector(
                    '[data-product-card="Daily notebook"]',
                    "the previous catalog page",
                )

                await shopper.fill('[data-testid="catalog-search"]', "lamp")
                await shopper.submit('[data-testid="catalog-search"]')
                await shopper.wait_for_text(
                    '[data-testid="catalog-search-status"]',
                    "1 product",
                )
                await shopper.wait_for_count("[data-product-card]", 1)
                await shopper.fill('[data-testid="catalog-search"]', "missing")
                await shopper.submit('[data-testid="catalog-search"]')
                await shopper.wait_for_text(
                    '[data-slot="empty"]',
                    "No products found",
                )
                await shopper.wait_for_count("[data-product-card]", 0)
                await shopper.fill('[data-testid="catalog-search"]', "")
                await shopper.submit('[data-testid="catalog-search"]')
                await shopper.wait_for_text(
                    '[data-testid="catalog-search-status"]',
                    "2 of 4 products",
                )
                await shopper.wait_for_count("[data-product-card]", 2)
                assert await shopper.attribute(
                    '[data-testid="catalog-previous"]', "disabled"
                ) == ""

                await shopper.fill(
                    '[data-testid="catalog-sort"]',
                    "price-descending",
                )
                await shopper.wait_for_selector(
                    '[data-product-card="Task lamp"]',
                    "the price-sorted catalog",
                )
                assert await shopper.evaluate_json(
                    "Array.from(document.querySelectorAll('[data-product-card]'))"
                    ".map(product => product.getAttribute('data-product-card'))"
                ) == ["Task lamp", "Canvas field bag"]

                await shopper.click('[data-testid="catalog-available"]')
                await shopper.wait_for_text(
                    '[data-testid="catalog-search-status"]',
                    "2 of 3 products",
                )
                await shopper.click('[data-testid="catalog-next"]')
                await shopper.wait_for_selector(
                    '[data-product-card="Daily notebook"]',
                    "the remaining available product",
                )
                await shopper.wait_for_count("[data-product-card]", 1)

                await shopper.fill('[data-testid="catalog-sort"]', "featured")
                await shopper.wait_for_text(
                    '[data-testid="catalog-search-status"]',
                    "2 of 3 products",
                )
                await shopper.wait_for_count("[data-product-card]", 2)
                await shopper.click('[data-testid="catalog-available"]')
                await shopper.wait_for_text(
                    '[data-testid="catalog-search-status"]',
                    "2 of 4 products",
                )
                await shopper.wait_for_selector(
                    '[data-product-card="Daily notebook"]',
                    "the restored default catalog",
                )

                await shopper.click('[data-product-id="2"] [data-product]')
                assert await shopper.evaluate(
                    "document.querySelector('catalog-page').cart_count"
                ) == 1
                await shopper.click('[data-testid="cart-trigger"]')
                await shopper.fill('[name="customer_name"]', "  ")
                await shopper.click('[data-testid="checkout"]')
                await shopper.wait_for_selector(
                    '[data-model-error="customer_name"]',
                    "the server-side customer-name error",
                )
                assert await shopper.attribute(
                    '[name="customer_name"]', "aria-invalid"
                ) == "true"
                await shopper.fill('[name="customer_name"]', "Ada Lovelace")
                await shopper.click('[data-testid="checkout"]')
                await shopper.wait_for_text(
                    '[data-testid="checkout-notice"]',
                    "Order #1 is ready for secure payment.",
                )
                await observer.wait_for_attribute(
                    '[data-product-card="Daily notebook"]',
                    "data-inventory",
                    "11",
                )

                assert await shopper.evaluate(
                    "document.querySelector('catalog-page').cart_count"
                ) == 0
                assert await observer.evaluate(
                    "document.querySelector('catalog-page')"
                    ".catalog_query.operation_path"
                ) == "/api/products/list"
                await shopper.click('[data-testid="payment-link"]')
                await shopper.wait_for_text("h1", "Northstar order #1")
                await shopper.click('[data-testid="complete-payment"]')
                await shopper.wait_for_text(
                    '[data-testid="order-history"]',
                    "Order #1",
                )
                await shopper.wait_for_text(
                    '[data-testid="order-history"]',
                    "paid",
                )
                assert shopper.exceptions == []
                assert observer.exceptions == []

    asyncio.run(run())


def test_store_bulk_inventory_update_refreshes_the_catalog():
    async def run():
        async with running_store() as url:
            async with Browser() as browser:
                catalog = await browser.new_page(url)
                await catalog.wait_for(
                    "document.querySelector('catalog-page')?.live_session?.transport "
                    "=== 'sse'",
                    "the catalog live session to connect",
                )
                inventory = await browser.new_page(url + "account/inventory/")
                await inventory.wait_for(
                    "document.querySelector('inventory-page')?._initialized === true",
                    "the inventory page to hydrate",
                )

                await inventory.click(
                    '[data-product-id="1"] [data-inventory-select]'
                )
                await inventory.click(
                    '[data-product-id="2"] [data-inventory-select]'
                )
                await inventory.fill('[data-testid="bulk-inventory-value"]', "9")
                await inventory.click('[data-testid="bulk-inventory-apply"]')
                await inventory.wait_for_text(
                    '[data-testid="inventory-notice"]',
                    "Updated 2 products.",
                )
                await inventory.wait_for_text(
                    '[data-product-id="1"]',
                    "9 in stock",
                )
                await catalog.wait_for_attribute(
                    '[data-product-card="Canvas field bag"]',
                    "data-inventory",
                    "9",
                )

                assert inventory.exceptions == []
                assert catalog.exceptions == []

    asyncio.run(run())


def test_store_reviews_paginate_submit_and_moderate_in_the_browser():
    async def run():
        async with running_store() as url:
            async with Browser() as browser:
                shopper = await browser.new_page(url)
                await shopper.wait_for(
                    "document.querySelector('catalog-page')?._initialized === true",
                    "the catalog to hydrate",
                )
                await shopper.click(
                    '[data-product-card="Canvas field bag"] '
                    "[data-product-details]"
                )
                await shopper.wait_for(
                    "document.querySelector('product-insights')?._initialized "
                    "=== true",
                    "the product insights to hydrate",
                )

                await shopper.click('[data-testid="browse-reviews"]')
                await shopper.wait_for_text("[data-review-rows]", "Noah")
                await shopper.wait_for(
                    "!document.querySelector('[data-testid=review-next]')"
                    ".hasAttribute('disabled')",
                    "the next review page to become available",
                )
                await shopper.click('[data-testid="review-next"]')
                await shopper.wait_for_text("[data-review-rows]", "Theo")
                await shopper.wait_for_text("[data-review-rows]", "Maya")

                await shopper.fill(
                    '[data-testid="review-form"] [name="author_name"]',
                    "  ",
                )
                await shopper.fill(
                    '[data-testid="review-form"] [name="rating"]',
                    "5",
                )
                await shopper.fill(
                    '[data-testid="review-form"] [name="body"]',
                    "Exactly the field bag I wanted.",
                )
                await shopper.submit(
                    '[data-testid="review-form"] [name="body"]'
                )
                await shopper.wait_for_text(
                    '[data-model-error="author_name"]',
                    "Enter at least two non-space characters.",
                )

                await shopper.fill(
                    '[data-testid="review-form"] [name="author_name"]',
                    "Ada",
                )
                await shopper.submit(
                    '[data-testid="review-form"] [name="body"]'
                )
                await shopper.wait_for_text(
                    '[data-testid="review-notice"]',
                    "awaiting approval",
                )

                moderator = await browser.new_page(url + "account/reviews/")
                await moderator.wait_for(
                    "document.querySelector('review-moderation-page')?._initialized "
                    "=== true",
                    "the moderation page to hydrate",
                )
                await moderator.wait_for_text(
                    '[data-testid="review-moderation-rows"]',
                    "Ada",
                )
                await moderator.click(
                    '[data-review-id="7"][data-review-action="published"]'
                )
                await moderator.wait_for_text(
                    '[data-testid="moderation-notice"]',
                    "Ada is now published.",
                )

                published = await browser.new_page(url)
                await published.wait_for(
                    "document.querySelector('catalog-page')?._initialized === true",
                    "the refreshed catalog to hydrate",
                )
                await published.click(
                    '[data-product-card="Canvas field bag"] '
                    "[data-product-details]"
                )
                await published.wait_for_text("[data-review-rows]", "Ada")

                assert shopper.exceptions == []
                assert moderator.exceptions == []
                assert published.exceptions == []

    asyncio.run(run())


def test_store_navigation_loads_hierarchical_page_bundles_without_a_reload():
    async def run():
        async with running_store() as url:
            async with Browser() as browser:
                direct_account = await browser.new_page(url + "account/")
                await direct_account.wait_for(
                    "document.querySelector('account-dashboard')?._initialized "
                    "=== true",
                    "the directly loaded account dashboard to hydrate",
                )
                assert await direct_account.evaluate(
                    "performance.getEntriesByType('resource').some("
                    "entry => entry.name.endsWith('/store/app.account.js'))"
                )
                assert direct_account.exceptions == []

                page = await browser.new_page(url)
                await page.wait_for(
                    "document.querySelector('catalog-page')?._initialized === true",
                    "the catalog to hydrate",
                )
                await page.wait_for(
                    "document.querySelector('catalog-page')"
                    ".live_session?.transport === 'sse'",
                    "the catalog live session to connect",
                )
                await page.evaluate("window.__storeNavigationMarker = 42")
                await page.evaluate(
                    "window.__catalogLiveSession = "
                    "document.querySelector('catalog-page').live_session"
                )

                await page.click('a[href="/story/"]')
                await page.wait_for(
                    "location.pathname === '/story/'",
                    "the story navigation",
                )
                await page.wait_for_text(
                    "h1",
                    "Useful things, considered carefully.",
                )
                assert await page.evaluate("window.__storeNavigationMarker") == 42
                assert await page.evaluate(
                    "window.__catalogLiveSession.transport"
                ) == "stopped"
                assert await page.evaluate(
                    "window.__catalogLiveSession._source"
                ) is None
                assert await page.evaluate(
                    "performance.getEntriesByType('resource').some("
                    "entry => entry.name.endsWith('/store/app.public.story.js'))"
                )

                await page.click('a[href="/account/"]')
                await page.wait_for(
                    "document.querySelector('account-dashboard')?._initialized "
                    "=== true",
                    "the account dashboard to hydrate",
                )
                await page.wait_for_text("account-dashboard", "Account overview")
                assert await page.evaluate("window.__storeNavigationMarker") == 42
                assert await page.evaluate(
                    "performance.getEntriesByType('resource').some("
                    "entry => entry.name.endsWith('/store/app.account.overview.js'))"
                )

                await page.click('a[href="/"]')
                await page.wait_for(
                    "document.querySelector('catalog-page')?._initialized === true",
                    "the restored catalog to hydrate",
                )
                await page.wait_for(
                    "document.querySelector('catalog-page')"
                    ".live_session?.transport === 'sse'",
                    "the restored live session to connect",
                )
                assert await page.evaluate("location.pathname") == "/"
                assert await page.evaluate("window.__storeNavigationMarker") == 42
                assert await page.evaluate(
                    "document.querySelector('catalog-page').live_session !== "
                    "window.__catalogLiveSession"
                )
                assert page.exceptions == []

    asyncio.run(run())


def test_store_navigation_falls_back_to_a_document_when_bundle_import_fails():
    async def run():
        async with running_store() as url:
            async with Browser() as browser:
                page = await browser.new_page(url)
                await page.wait_for(
                    "document.querySelector('catalog-page')?._initialized === true",
                    "the catalog to hydrate",
                )
                await page.evaluate("window.__storeNavigationMarker = 42")
                await page.session.send("Network.enable")
                await page.session.send(
                    "Network.setBlockedURLs",
                    {"urls": ["*app.public.story.js*"]},
                )

                await page.click('a[href="/story/"]')
                await page.wait_for(
                    "location.pathname === '/story/' "
                    "&& document.querySelector('h1')?.textContent.includes("
                    "'Useful things')",
                    "the full-page story fallback",
                )

                assert await page.evaluate(
                    "window.__storeNavigationMarker === undefined"
                )
                assert await page.text("h1") == (
                    "Useful things, considered carefully."
                )

    asyncio.run(run())


def test_store_visitor_feed_appends_cursor_pages_and_observes_its_sentinel():
    async def run():
        async with running_store() as url:
            async with Browser() as browser:
                page = await browser.new_page(url + "account/visitors/")
                await page.wait_for_selector("visitor-activity-page")
                await asyncio.sleep(0.2)
                assert page.exceptions == []
                await page.wait_for(
                    "document.querySelector('visitor-activity-page')?._initialized "
                    "=== true",
                    "the visitor feed to hydrate",
                )
                await page.wait_for_count("[data-visitor-event]", 4)
                await page.wait_for_count(
                    '[data-testid="visitor-log"] '
                    '[data-slot="streaming-log-line"]',
                    4,
                )
                assert await page.evaluate(
                    "document.querySelector('line-chart svg').namespaceURI"
                ) == "http://www.w3.org/2000/svg"

                await page.click('[data-slot="infinite-scroll-button"]')
                await page.wait_for(
                    "document.querySelectorAll('[data-visitor-event]').length >= 8",
                    "the next visitor page to append",
                )
                await page.evaluate(
                    "document.querySelector('[data-slot=infinite-scroll-sentinel]')"
                    ".scrollIntoView()"
                )
                await page.wait_for_count("[data-visitor-event]", 12)
                await page.wait_for_count(
                    '[data-testid="visitor-log"] '
                    '[data-slot="streaming-log-line"]',
                    12,
                )

                assert await page.evaluate_json(
                    "Array.from(document.querySelectorAll('[data-visitor-event]'))"
                    ".map(row => Number(row.dataset.visitorEvent))"
                ) == [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
                assert await page.attribute(
                    '[data-visitor-event="8"] time',
                    "datetime",
                ) == "2026-08-18"
                assert await page.attribute(
                    '[data-slot="infinite-scroll-button"]',
                    "disabled",
                ) == ""

                await page.click('[data-testid="simulate-visitor"]')
                await page.wait_for_count("[data-visitor-event]", 13)
                await page.wait_for_count(
                    '[data-testid="visitor-log"] '
                    '[data-slot="streaming-log-line"]',
                    13,
                )
                assert await page.attribute(
                    "[data-visitor-event]:first-child",
                    "data-visitor-event",
                ) == "13"
                # The stream's trailing sentinel is not a log line.
                lines = await page.evaluate_json(
                    "Array.from(document.querySelectorAll('[data-testid=visitor-log] "
                    "[data-slot=streaming-log-line]')).map(line => line.textContent)"
                )
                assert "/products/canvas-field-bag/" in lines[-1]
                assert page.exceptions == []

    asyncio.run(run())
