"""Browser declarations can name absent SSR state without a browser runtime."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm, transpile_llvm_module
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_browser_state_stays_absent_across_aliases_and_collection(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import AbortController, IntersectionObserver

class State:
    observer: IntersectionObserver | None
    def __init__(self):
        self.observer = None
        self.controller: AbortController | None = None
        self.text = "keep" + str(42)
class Child(State):
    def clear(self) -> None:
        self.observer = None
def absent(state: State) -> bool:
    return state.controller is None and state.observer is None
def main() -> str:
    gc_set_threshold(1)
    child = Child()
    values: list[State] = [child]
    child.clear()
    gc_collect()
    return str(absent(values[0])) + ":" + values[0].text
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "True:keep42"
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_navigation_and_scroll_render_without_browser_collaborators(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.server import CursorPageRequest
from pyjs.web.domx import div
from pyjs.web.navigation import NavigationLayout
from pyjs.web.ssr import render_html
from pyjs.web.ui.infinite_scroll import InfiniteScroll

async def browser_only(request: CursorPageRequest) -> None:
    browser_api.fetch(request.after)

def main() -> str:
    gc_set_threshold(1)
    scroll = InfiniteScroll("next-page")
    scroll.on_load(browser_only)
    layout = NavigationLayout(div(scroll))
    layout.add(layout.outlet)
    gc_collect()
    assert layout.controller is None
    return render_html(layout)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert 'data-cursor="next-page"' in result.native.stdout
    assert result.native.stderr == ""


@pytest.mark.parametrize("source, message", [
    ('''from pyjs.web.dom import AbortController
def main() -> bool:
    value = AbortController()
    return value is None
''', "LLVM indirect calls are not implemented"),
    ('''from pyjs.web.dom import AbortController
class Fake(AbortController):
    pass
def main() -> bool:
    return Fake() is None
''', "cannot inherit browser-only declarations"),
    ('''from pyjs.web.dom import AbortController
def read(value: AbortController) -> bool:
    return value.signal is None
def main() -> bool:
    value: AbortController | None = None
    if value is not None:
        return read(value)
    return False
''', "cannot resolve field signal on AbortController"),
])
def test_browser_storage_does_not_supply_a_runtime(source, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(source)


@pytest.mark.parametrize("annotation", ["AbortController", "AbortController | None", "list[AbortController | None]"])
def test_browser_state_has_no_host_copy_in_abi(annotation):
    with pytest.raises(LLVMUnsupported, match="library input type AbortController is not supported"):
        transpile_llvm_module(f'''
from pyjs.web.dom import AbortController
def main(value: {annotation}) -> str:
    return "no host browser handles"
''', target="library")


SCROLL_OVERRIDE = '''
from collections.abc import Callable
from pyjs.web.ssr import render_html
from pyjs.web.ui.infinite_scroll import InfiniteScroll

class Active(InfiniteScroll):
    def on_load(self, callback: Callable[[], None]) -> None:
        self.setAttribute("data-active", "yes")

def callback() -> None:
    pass
'''


@pytest.mark.parametrize("optimize", [0, 2])
def test_concrete_scroll_registration_override_runs(tmp_path, optimize):
    # Unlike the erased builtin wrapper, an ordinary override evaluates its
    # arguments. Use a native-supported callback, not an async function value.
    result = LLVM().assert_matches_python(SCROLL_OVERRIDE + '''
def main() -> str:
    scroll = Active("next")
    scroll.on_load(callback)
    return render_html(scroll)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert 'data-active="yes"' in result.native.stdout
    assert result.native.stderr == ""


def test_base_scroll_registration_cannot_discard_an_override():
    with pytest.raises(LLVMUnsupported, match="erased on_load overrides require a concrete application method call"):
        transpile_llvm(SCROLL_OVERRIDE + '''
def register(scroll: InfiniteScroll) -> None:
    scroll.on_load(callback)
def main() -> str:
    scroll = Active("next")
    register(scroll)
    return render_html(scroll)
''')
