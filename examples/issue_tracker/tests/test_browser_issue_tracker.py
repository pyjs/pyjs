import asyncio
import os
import subprocess
import sys

import pytest
from pyjs.tooling import stop_process
from pyjs.tooling.browser import Browser, free_port, wait_for_http

pytestmark = pytest.mark.pyjs_python


def test_issue_workflow_uses_nested_typed_api_resources():
    async def run():
        port = free_port()
        url = f"http://127.0.0.1:{port}/"
        environment = os.environ.copy()
        environment["PYJS_PORT"] = str(port)
        environment["PYTHONUNBUFFERED"] = "1"
        server = subprocess.Popen(
            [sys.executable, "-m", "pyjs_examples.issue_tracker"],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            await wait_for_http(url, timeout=120)
            async with Browser() as browser:
                page = await browser.new_page(url)
                await page.wait_for_selector("issue-tracker")
                await page.wait_for(
                    "document.querySelector('issue-tracker')._initialized === true",
                    "the issue tracker to hydrate",
                )
                await page.wait_for_attribute(
                    "issue-tracker",
                    "data-project-api",
                    "PYJS",
                )
                await page.wait_for_attribute(
                    "issue-tracker",
                    "data-milestone-api",
                    "0.0.3",
                )
                await page.wait_for(
                    "document.querySelector('issue-tracker')"
                    ".live_session.transport === 'sse'",
                    "the issue tracker live session to connect",
                )

                observer = await browser.new_page(url)
                await observer.wait_for_selector("issue-tracker")
                await observer.wait_for(
                    "document.querySelector('issue-tracker')._initialized === true",
                    "the observing issue tracker to hydrate",
                )
                await observer.wait_for(
                    "document.querySelector('issue-tracker')"
                    ".live_session.transport === 'sse'",
                    "the observing live session to connect",
                )
                assert await observer.evaluate(
                    "document.querySelector('issue-tracker')"
                    ".live_session._subscription.length > 0"
                ) is True
                assert "?subscription=" in await observer.evaluate(
                    "document.querySelector('issue-tracker')"
                    ".live_session._source.url"
                )
                assert await observer.evaluate(
                    "document.querySelector('issue-tracker')"
                    ".issue_query.operation_path"
                ) == "/api/issues/list"
                await observer.evaluate(
                    "(() => {"
                    "const originalFetch = window.fetch;"
                    "window.__pyjsLiveRefreshes = 0;"
                    "window.__pyjsDirectIssueQueries = 0;"
                    "window.fetch = (...args) => {"
                    "const path = String(args[0]);"
                    "if (path.endsWith('/_live/refresh')) "
                    "window.__pyjsLiveRefreshes += 1;"
                    "if (path.endsWith('/issues/list')) "
                    "window.__pyjsDirectIssueQueries += 1;"
                    "return originalFetch(...args);"
                    "};"
                    "return true;"
                    "})()"
                )
                assert await observer.text('[data-testid="issue-count"]') == (
                    "3 issues"
                )

                assert await page.text('[data-testid="project-name"]') == "PyJS"
                assert await page.text('[data-testid="issue-count"]') == "3 issues"
                assert await page.text('[data-testid="open-count"]') == "2"
                assert await page.text('[data-testid="closed-count"]') == "1"
                assert await page.text('[data-testid="detail-title"]') == (
                    "Tree-shake unused client API operations"
                )
                assert await page.text('[data-testid="comment-count"]') == (
                    "2 comments"
                )

                await page.click('[data-testid="filter-closed"]')
                await page.wait_for_count('[data-testid="issue-card"]', 1)
                assert await page.text('[data-testid="issue-title"]') == (
                    "Document resource permissions"
                )

                await page.click('[data-testid="filter-all"]')
                await page.wait_for_count('[data-testid="issue-card"]', 3)
                await page.fill('[aria-label="Search issues"]', "stream")
                await page.click('[data-testid="search-issues"]')
                await page.wait_for_count('[data-testid="issue-card"]', 1)
                assert await page.text('[data-testid="issue-title"]') == (
                    "Stream project activity to connected clients"
                )

                await page.click('[data-testid="filter-all"]')
                await page.wait_for_count('[data-testid="issue-card"]', 3)
                await page.fill('[name="title"]', "No")
                await page.click('[data-testid="save-issue"]')
                await page.wait_for_text(
                    '[data-testid="save-status"]',
                    "Correct the highlighted fields",
                )

                assert await page.text('[data-model-error="title"]') == (
                    "An issue title must contain at least three characters."
                )
                await page.wait_for_attribute(
                    '[name="title"]',
                    "aria-invalid",
                    "true",
                )
                assert await page.text('[data-testid="issue-count"]') == "3 issues"

                await page.fill(
                    '[name="title"]',
                    "Exercise nested relationship metadata",
                )
                await page.fill(
                    '[name="description"]',
                    "Keep models rich while resource relationships stay explicit.",
                )
                await page.fill('[name="priority"]', "high")
                await page.click('[data-testid="save-issue"]')
                await page.wait_for_text(
                    '[data-testid="save-status"]',
                    "Created PYJS-43",
                )

                assert await page.text('[data-testid="issue-count"]') == "4 issues"
                assert await page.text('[data-testid="detail-title"]') == (
                    "Exercise nested relationship metadata"
                )
                assert await page.text('[data-testid="comment-count"]') == (
                    "0 comments"
                )
                await page.wait_for_count('[data-model-error="title"]', 0)
                await observer.wait_for_text(
                    '[data-testid="issue-count"]',
                    "4 issues",
                )
                await observer.wait_for_count('[data-testid="issue-card"]', 4)
                assert "Exercise nested relationship metadata" in await observer.texts(
                    '[data-testid="issue-title"]'
                )

                await page.fill(
                    '[data-testid="comment-input"]',
                    "The nested comment resource works.",
                )
                await page.click('[data-testid="add-comment"]')
                await page.wait_for_text(
                    '[data-testid="comment-status"]',
                    "Comment added",
                )
                assert await page.text('[data-testid="comment-count"]') == (
                    "1 comment"
                )

                await page.click('[data-testid="close-issue"]')
                await page.wait_for_attribute(
                    '[data-testid="close-issue"]',
                    "disabled",
                    "",
                )
                assert await page.text('[data-testid="open-count"]') == "2"
                assert await page.text('[data-testid="closed-count"]') == "2"
                assert await observer.evaluate(
                    "window.__pyjsLiveRefreshes"
                ) == 0
                assert await observer.evaluate(
                    "window.__pyjsDirectIssueQueries"
                ) == 0
                assert page.exceptions == []
                assert observer.exceptions == []
        finally:
            stop_process(server)

    asyncio.run(run())
