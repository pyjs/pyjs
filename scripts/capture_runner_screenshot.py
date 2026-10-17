#!/usr/bin/env python3

import asyncio
import json
import os
import subprocess
from pathlib import Path

from pyjs.tooling import stop_process
from pyjs.tooling.browser import Browser, BrowserPage, free_port, wait_for_http

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_ROOT = ROOT / "examples"
CALCULATOR_ROOT = EXAMPLES_ROOT / "calculator"
PYTHON = ROOT / ".venv" / "bin" / "python"
OUTPUT = ROOT / "screenshots"
CALCULATOR_PYTHONPATH = os.pathsep.join(
    str(path)
    for path in (
        CALCULATOR_ROOT / "tests",
        CALCULATOR_ROOT,
        os.environ.get("PYTHONPATH"),
    )
    if path
)


async def run_browser_pytest(
    daemon_port: int,
    cwd: Path = CALCULATOR_ROOT,
    test_paths: tuple[str, ...] = (),
) -> None:
    command = [
        PYTHON,
        "-m",
        "pytest",
        "-q",
        *test_paths,
        "--pyjs-target=web",
        f"--pyjs-daemon-port={daemon_port}",
    ]
    result = await asyncio.to_thread(subprocess.run, command, cwd=cwd, check=False)
    if result.returncode:
        raise RuntimeError(f"pytest exited with code {result.returncode}")


async def wait_for_runner(page: BrowserPage) -> None:
    await page.wait_for(
        """location.href.startsWith('http://127.0.0.1:')
            && document.readyState === 'complete'
            && (document.querySelector('#status')?.textContent || '')
                .toLowerCase().includes('connected')""",
        "runner page to connect to the daemon",
        timeout=20,
    )


def assert_runner_summary(summary: dict, expected_run: int) -> None:
    row_count = summary.get("rowCount")
    if not isinstance(row_count, int) or row_count <= 0:
        raise RuntimeError(f"Runner did not report test rows: {json.dumps(summary)}")
    if summary.get("uniqueRowCount") != row_count:
        raise RuntimeError(f"Runner contains duplicate test rows: {json.dumps(summary)}")
    if f"Run #{expected_run}" not in summary.get("statusText", ""):
        raise RuntimeError(f"Runner did not advance to Run #{expected_run}: {json.dumps(summary)}")


async def runner_summary(page: BrowserPage) -> dict:
    return await page.evaluate_json(
        """(() => {
            const rows = Array.from(document.querySelectorAll('.test-row-nodeid'))
                .map((node) => node.textContent || '');
            return {
                rowCount: rows.length,
                uniqueRowCount: new Set(rows).size,
                statusText: document.querySelector('#status')?.textContent || '',
            };
        })()"""
    )


async def exercise_synthetic_reset(page: BrowserPage) -> None:
    value = await page.evaluate_json(
        """(() => {
            const app = document.querySelector('browser-runner-app');
            if (!app) throw new Error('runner app element is not available');
            const selected = [
                'synthetic/test_one.py::test_one',
                'synthetic/test_two.py::test_two',
            ];
            const summarize = () => {
                const rows = Array.from(document.querySelectorAll('.test-row-nodeid'))
                    .map((node) => node.textContent || '');
                return {
                    rowCount: rows.length,
                    uniqueRowCount: new Set(rows).size,
                    statusText: document.querySelector('#status')?.textContent || '',
                };
            };
            app.prepareRunSession(selected, selected[0], () => {});
            app.setStatus(app.summarizeResults());
            const first = summarize();
            app.prepareRunSession(selected, selected[0], () => {});
            app.setStatus(app.summarizeResults());
            return {first, second: summarize()};
        })()"""
    )
    assert_runner_summary(value["first"], 1)
    assert_runner_summary(value["second"], 2)
    if value["first"]["rowCount"] != value["second"]["rowCount"]:
        raise RuntimeError(f"Runner row count changed across resets: {json.dumps(value)}")


async def assert_previous_frame_selectable(page: BrowserPage) -> None:
    value = await page.evaluate_json(
        """(() => {
            const app = document.querySelector('browser-runner-app');
            if (!app) throw new Error('runner app element is not available');
            const currentNodeid = app.viewer?.getCurrentFrameNodeid() || '';
            const target = (app._testStates || []).find((state) => (
                state.hasPreview
                && state.nodeid !== currentNodeid
                && String(state.nodeid || '').includes('test_browser_')
            ));
            if (!target) {
                return {
                    targetNodeid: '',
                    currentNodeid,
                    availableNodeids: (app._testStates || [])
                        .filter((state) => state.hasPreview)
                        .map((state) => state.nodeid),
                };
            }
            app.selectTest(target.nodeid);
            return {
                targetNodeid: target.nodeid,
                currentNodeid: app.viewer?.getCurrentFrameNodeid() || '',
                activeTitle: document.querySelector('iframe.runner-frame.active')
                    ?.getAttribute('title') || '',
                frameHostNoUi: document.querySelector('.frame-host')
                    ?.classList.contains('no-ui') || false,
            };
        })()"""
    )
    if not value["targetNodeid"]:
        raise RuntimeError(f"Runner did not retain a selectable iframe: {json.dumps(value)}")
    if value["currentNodeid"] != value["targetNodeid"]:
        raise RuntimeError(f"Runner did not select the retained iframe: {json.dumps(value)}")
    if value["targetNodeid"] not in value["activeTitle"]:
        raise RuntimeError(f"Runner did not activate the retained iframe: {json.dumps(value)}")
    if value["frameHostNoUi"]:
        raise RuntimeError(f"Runner hid the retained iframe: {json.dumps(value)}")


async def assert_frame_eviction(page: BrowserPage) -> None:
    value = await page.evaluate_json(
        """(() => {
            const app = document.querySelector('browser-runner-app');
            if (!app) throw new Error('runner app element is not available');
            const before = (app._preservedEntries || []).length;
            app.evictPreservedFramesIfNeeded(2);
            return {before, after: (app._preservedEntries || []).length};
        })()"""
    )
    if not isinstance(value["before"], int) or value["before"] <= 2:
        raise RuntimeError(f"Runner did not retain enough frames: {json.dumps(value)}")
    if value["after"] != 2:
        raise RuntimeError(f"Runner did not evict frames to the limit: {json.dumps(value)}")


async def capture_calculator(page: BrowserPage) -> dict:
    value = await page.evaluate_json(
        """(() => {
            const app = document.querySelector('browser-runner-app');
            const state = (app?._testStates || []).find((candidate) => (
                candidate.hasPreview
                && String(candidate.nodeid || '').includes('test_calculator_visual_showcase')
            ));
            if (!app || !state) return {error: 'calculator showcase iframe was not preserved'};
            app.selectTest(state.nodeid);
            const frame = document.querySelector('iframe.runner-frame.active');
            const frameDocument = frame?.contentDocument;
            const card = frameDocument?.querySelector('[data-testid="calculator-card"]');
            const display = frameDocument?.querySelector('[data-testid="calculator-display"]');
            if (!frame || !frameDocument || !card || !display) {
                return {error: 'calculator showcase elements were not available'};
            }
            const rect = (element) => {
                const bounds = element.getBoundingClientRect();
                return {
                    left: bounds.left,
                    top: bounds.top,
                    right: bounds.right,
                    bottom: bounds.bottom,
                    width: bounds.width,
                    height: bounds.height,
                };
            };
            const frameRect = rect(frame);
            const cardRect = rect(card);
            const cardStyle = frame.contentWindow.getComputedStyle(card);
            const frameHost = frame.closest('.frame-host');
            return {
                nodeid: state.nodeid,
                display: display.textContent || '',
                keyCount: frameDocument.querySelectorAll('[data-key]').length,
                frame: frameRect,
                card: cardRect,
                viewport: {
                    width: frame.contentWindow.innerWidth,
                    height: frame.contentWindow.innerHeight,
                },
                styles: {
                    frameDisplay: getComputedStyle(frame).display,
                    frameHostDisplay: frameHost ? getComputedStyle(frameHost).display : '',
                    backgroundColor: cardStyle.backgroundColor,
                    borderRadius: cardStyle.borderRadius,
                    boxShadow: cardStyle.boxShadow,
                },
                page: {
                    scrollX: window.scrollX,
                    scrollY: window.scrollY,
                    width: window.innerWidth,
                    height: window.innerHeight,
                },
            };
        })()"""
    )
    if error := value.get("error"):
        raise RuntimeError(f"Could not inspect calculator: {error}")
    if float(value["display"]) != 36 or value["keyCount"] != 19:
        raise RuntimeError(f"Calculator content is incorrect: {json.dumps(value)}")
    if value["styles"]["frameDisplay"] == "none" or value["styles"]["frameHostDisplay"] == "none":
        raise RuntimeError(f"Calculator iframe is hidden: {json.dumps(value)}")
    if value["card"]["width"] <= 0 or value["card"]["height"] <= 0:
        raise RuntimeError(f"Calculator has zero-sized geometry: {json.dumps(value)}")
    horizontal_offset = abs(
        value["card"]["left"] + value["card"]["width"] / 2 - value["viewport"]["width"] / 2
    )
    vertical_offset = abs(
        value["card"]["top"] + value["card"]["height"] / 2 - value["viewport"]["height"] / 2
    )
    if horizontal_offset > 2 or vertical_offset > 2:
        raise RuntimeError(f"Calculator is not centered: {json.dumps(value)}")
    styles = value["styles"]
    if styles["backgroundColor"] == "rgba(0, 0, 0, 0)":
        raise RuntimeError(f"Calculator Tailwind styles are missing: {json.dumps(value)}")
    if styles["borderRadius"] == "0px" or styles["boxShadow"] == "none":
        raise RuntimeError(f"Calculator surface styling is missing: {json.dumps(value)}")

    (OUTPUT / "calculator.json").write_text(
        json.dumps(value, indent=2) + "\n",
        encoding="utf-8",
    )
    padding = 20
    clip = {
        "x": max(
            0,
            value["page"]["scrollX"] + value["frame"]["left"] + value["card"]["left"] - padding,
        ),
        "y": max(
            0,
            value["page"]["scrollY"] + value["frame"]["top"] + value["card"]["top"] - padding,
        ),
        "width": value["card"]["width"] + padding * 2,
        "height": value["card"]["height"] + padding * 2,
        "scale": 1,
    }
    await page.screenshot(OUTPUT / "calculator.png", clip=clip)
    return value


async def select_panel(page: BrowserPage, panel: str) -> None:
    await page.evaluate(
        f"document.querySelector('browser-runner-app')?.viewer?.selectPanel({json.dumps(panel)})"
    )
    await page.wait_for_frames()


async def capture_theme(page: BrowserPage, theme: str, filename: str) -> None:
    await page.set_color_scheme(theme)
    await page.wait_for_frames()
    await page.screenshot(OUTPUT / filename)


async def capture_narrow(page: BrowserPage) -> None:
    await page.set_viewport(580, 900)
    await page.wait_for_frames()
    value = await page.evaluate_json(
        """({
            viewportWidth: innerWidth,
            documentWidth: document.documentElement.scrollWidth,
            sidebarHeight: document.querySelector('runner-sidebar')
                ?.getBoundingClientRect().height || 0,
            viewerHeight: document.querySelector('runner-viewer')
                ?.getBoundingClientRect().height || 0,
        })"""
    )
    if (
        value["documentWidth"] > value["viewportWidth"]
        or value["sidebarHeight"] <= 0
        or value["viewerHeight"] <= 0
    ):
        raise RuntimeError(f"Runner narrow layout overflowed or collapsed: {json.dumps(value)}")
    await page.screenshot(OUTPUT / "browser-runner-ui-narrow.png", full_page=True)
    await page.clear_viewport()


async def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    daemon_port = free_port()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = CALCULATOR_PYTHONPATH
    daemon = subprocess.Popen(
        [
            PYTHON,
            "-m",
            "pyjs.testing.daemon",
            "--host",
            "127.0.0.1",
            "--port",
            str(daemon_port),
            "--idle-seconds",
            "30",
            "--project-root",
            EXAMPLES_ROOT,
            "--cache-dir",
            EXAMPLES_ROOT / ".pytest_cache" / "d" / "pyjs",
        ],
        cwd=CALCULATOR_ROOT,
        env=environment,
    )
    try:
        await wait_for_http(f"http://127.0.0.1:{daemon_port}/healthz", timeout=10)
        async with Browser() as browser:
            page = await browser.new_page(f"http://127.0.0.1:{daemon_port}/")
            await page.set_viewport(1440, 1100)
            await page.bring_to_front()
            await wait_for_runner(page)
            await exercise_synthetic_reset(page)

            await run_browser_pytest(daemon_port)
            summary = await runner_summary(page)
            if not isinstance(summary.get("rowCount"), int) or summary["rowCount"] <= 0:
                raise RuntimeError(f"Runner did not report real pytest rows: {json.dumps(summary)}")
            calculator_state = await capture_calculator(page)
            await assert_previous_frame_selectable(page)

            await capture_theme(page, "dark", "browser-runner-ui.png")
            await select_panel(page, "output")
            await capture_theme(page, "light", "browser-runner-ui-light.png")
            await select_panel(page, "preview")
            await capture_theme(page, "dark", "browser-runner-ui.png")
            await capture_narrow(page)
            await assert_frame_eviction(page)
            await run_browser_pytest(
                daemon_port,
                ROOT,
                ("tests/testing/test_browser_runner_ui.py",),
            )
            if page.exceptions:
                raise RuntimeError(f"Browser errors: {'; '.join(page.exceptions)}")

            print(f"Saved browser runner screenshots to {OUTPUT}")
            print(
                "Calculator geometry: "
                + json.dumps(
                    {
                        "viewport": calculator_state["viewport"],
                        "card": calculator_state["card"],
                    }
                )
            )
    finally:
        stop_process(daemon)


if __name__ == "__main__":
    asyncio.run(main())
