#!/usr/bin/env python3

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pyjs.tooling import stop_process
from pyjs.tooling.browser import Browser, BrowserPage, free_port, wait_for_http

PROJECT_ROOT = Path.cwd()
OUTPUT = PROJECT_ROOT / "screenshots"


def server_command() -> list[str | Path]:
    local_application = PROJECT_ROOT / "chat.py"
    if local_application.is_file():
        return [sys.executable, local_application]
    return [sys.executable, "-m", "pyjs_examples.chat"]


async def fill_and_submit(page: BrowserPage, test_id: str, value: str) -> None:
    selector = f'[data-testid="{test_id}"]'
    await page.fill(selector, value)
    await page.submit(selector)


async def state(page: BrowserPage) -> dict:
    return {
        "name": await page.attribute("chat-app", "name"),
        "room": await page.attribute("chat-app", "room"),
        "connection": await page.attribute("chat-app", "connection"),
        "membership": await page.attribute("chat-app", "membership"),
        "rooms": await page.attributes("[data-room]", "data-room"),
        "users": await page.attributes("[data-user]", "data-user"),
        "messages": await page.texts("[data-message-id] p"),
        "memberCount": await page.text('[data-testid="member-count"]'),
    }


def verify_state(value: dict, expected_name: str) -> None:
    expected = {
        "name": expected_name,
        "room": "product-design",
        "connection": "connected",
        "membership": "free",
        "rooms": ["general", "product-design"],
        "users": ["Alice", "Bob"],
        "messages": [
            "Welcome to the new room, Bob!",
            "Thanks Alice — real-time chat is working.",
        ],
        "memberCount": "2 people",
    }
    if value != expected:
        raise RuntimeError(f"Unexpected {expected_name} state: {json.dumps(value)}")


async def exercise(browser: Browser, alice: BrowserPage, bob: BrowserPage) -> dict:
    await alice.wait_for_selector('[data-testid="name-input"]', "Alice's chat")
    await bob.wait_for_selector('[data-testid="name-input"]', "Bob's chat")
    await alice.wait_for(
        "customElements.get('chat-app') !== undefined",
        "Alice's hydrated chat",
    )
    await bob.wait_for(
        "customElements.get('chat-app') !== undefined",
        "Bob's hydrated chat",
    )

    await fill_and_submit(alice, "name-input", "Alice")
    await alice.wait_for_attribute(
        "chat-app",
        "connection",
        "connected",
        "Alice's connection",
    )
    await fill_and_submit(bob, "name-input", "Bob")
    await bob.wait_for_attribute(
        "chat-app",
        "connection",
        "connected",
        "Bob's connection",
    )

    await fill_and_submit(alice, "room-input", "product-design")
    await bob.wait_for_selector(
        '[data-room="product-design"]',
        "the new room in Bob's tab",
    )
    await bob.click('[data-room="product-design"]')
    await alice.wait_for_count("[data-user]", 2, "both room members")

    await fill_and_submit(alice, "message-input", "Welcome to the new room, Bob!")
    await bob.wait_for_text(
        '[data-testid="message-list"]',
        "Welcome",
        "Alice's message in Bob's tab",
    )
    await fill_and_submit(bob, "message-input", "Thanks Alice — real-time chat is working.")
    await alice.wait_for_text(
        '[data-testid="message-list"]',
        "Thanks Alice",
        "Bob's message in Alice's tab",
    )

    alice_state = await state(alice)
    bob_state = await state(bob)
    verify_state(alice_state, "Alice")
    verify_state(bob_state, "Bob")
    await alice.screenshot(OUTPUT / "chat-alice.png")
    await bob.screenshot(OUTPUT / "chat-bob.png")

    await alice.click('[data-testid="membership-trigger"]')
    await alice.wait_for_attribute(
        '[data-slot="sheet-content"]',
        "data-state",
        "open",
        "the workspace membership sheet",
    )
    await alice.click('[data-testid="upgrade-membership"]')
    await alice.wait_for_attribute(
        "chat-app",
        "membership",
        "pro",
        "Alice's upgraded workspace membership",
    )
    await bob.wait_for_attribute(
        "chat-app",
        "membership",
        "pro",
        "Bob's updated workspace membership",
    )
    bob_membership = await bob.attribute("chat-app", "membership")
    await alice.screenshot(OUTPUT / "chat-membership.png")
    await alice.click('[data-slot="sheet-close"]')

    await browser.close_page(bob)
    await alice.wait_for_count("[data-user]", 1, "Bob's departure in Alice's tab")
    remaining_users = await alice.attributes("[data-user]", "data-user")
    await alice.click('[data-testid="assistant-destination"]')
    await alice.wait_for_selector(
        '[data-slot="questionnaire"]',
        "the assistant questionnaire",
    )
    await alice.wait_for_selector(
        '[data-slot="attachment"]',
        "the assistant attachment",
    )
    await alice.screenshot(OUTPUT / "chat-assistant.png")
    return {
        "alice": alice_state,
        "bob": bob_state,
        "assistant": {
            "questionnaires": await alice.evaluate(
                'document.querySelectorAll("[data-slot=questionnaire]").length'
            ),
            "attachments": await alice.evaluate(
                'document.querySelectorAll("[data-slot=attachment]").length'
            ),
        },
        "remainingUsers": remaining_users,
        "membership": await alice.attribute("chat-app", "membership"),
        "bobMembership": bob_membership,
        "errors": alice.exceptions + bob.exceptions,
    }


async def main() -> None:
    app_port = free_port()
    app_url = f"http://127.0.0.1:{app_port}/"
    environment = os.environ.copy()
    environment["PYJS_PORT"] = str(app_port)
    with tempfile.TemporaryFile(mode="w+") as server_log:
        server = subprocess.Popen(
            server_command(),
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        try:
            await wait_for_http(app_url, timeout=20)
            async with Browser() as browser:
                alice = await browser.new_page(app_url)
                bob = await browser.new_page(app_url)
                await alice.set_viewport(1440, 900)
                await bob.set_viewport(1440, 900)
                result = await exercise(browser, alice, bob)
                if result["errors"]:
                    raise RuntimeError(f"Browser errors: {'; '.join(result['errors'])}")
                OUTPUT.mkdir(parents=True, exist_ok=True)
                (OUTPUT / "chat.json").write_text(
                    json.dumps(result, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(json.dumps(result, indent=2))
        except BaseException:
            stop_process(server)
            server_log.seek(0)
            sys.stderr.write(server_log.read())
            raise
        finally:
            stop_process(server)


if __name__ == "__main__":
    asyncio.run(main())
