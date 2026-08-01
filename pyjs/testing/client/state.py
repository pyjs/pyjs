"""Typed state and protocol models for the browser runner client."""

from pyjs import js
from pyjs.web.html import HTMLIFrameElement


@js
class ConsoleLine:
    def __init__(self, level: str, text: str):
        self.level = level
        self.text = text


@js
class TestManifestEntry:
    def __init__(self, nodeid: str):
        self.nodeid = nodeid


@js
class RenderArtifact:
    def __init__(
        self,
        name: str,
        data_url: str,
        pixel_threshold: int,
        max_different_pixel_ratio: float,
        element_id: str = "",
        animation_time_ms: float | None = None,
    ):
        self.name = name
        self.dataUrl = data_url
        self.pixelThreshold = pixel_threshold
        self.maxDifferentPixelRatio = max_different_pixel_ratio
        self.elementId = element_id
        self.animationTimeMs = animation_time_ms


@js
class TestResult:
    def __init__(
        self,
        nodeid: str,
        outcome: str,
        artifacts: list[RenderArtifact],
        error: str = "",
    ):
        self.nodeid = nodeid
        self.outcome = outcome
        self.artifacts = artifacts
        self.error = error


@js
class FetchOptions:
    def __init__(self, cache: str):
        self.cache = cache


@js
class RegisterBrowserMessage:
    def __init__(self):
        self.type = "register_browser"


@js
class RunBundleMessage:
    def __init__(self):
        self.type = ""
        self.run_id = ""
        self.nodeids: list[str] = []
        self.selected_nodeids: list[str] | None = None
        self.current_nodeid: str | None = None
        self.max_preserved_iframes = 10


@js
class TestResultsMessage:
    def __init__(self, run_id: str, results: list[TestResult]):
        self.type = "test_results"
        self.run_id = run_id
        self.results = results


@js
class SingleTestRun:
    def __init__(self, result: TestResult, console_lines: list[ConsoleLine]):
        self.result = result
        self.consoleLines = console_lines


@js
class TestState:
    def __init__(self, nodeid: str):
        self.nodeid = nodeid
        self.status = "pending"
        self.hasPreview = False
        self.error = ""
        self.consoleLines: list[ConsoleLine] = []


@js
class PreservedEntry:
    def __init__(self, nodeid: str, frame: HTMLIFrameElement, outcome: str):
        self.nodeid = nodeid
        self.frame = frame
        self.outcome = outcome
