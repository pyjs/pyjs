import shutil
import subprocess

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import _fail_allocations, run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_class_views_have_distinct_identity_and_outlive_wrapper_references(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import DOMTokenList
from pyjs.web.domx import CustomElement, div
class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.classList.add("panel")
class Saved:
    def __init__(self, view: DOMTokenList):
        self.view = view
def make() -> DOMTokenList:
    return Panel().classList
def change(view: DOMTokenList | None) -> None:
    if view is not None:
        view.add("later")
def main() -> str:
    gc_set_threshold(1)
    root = div({"class": "start"})
    first = root.classList
    second = root.classList
    assert first is first
    assert first is not second
    assert first != second
    assert [first, second] == [first, second]
    assert [first] != [second]
    assert "text" != first
    assert bool(first)
    stored = Saved(first)
    views = [first, second, make()]
    gc_collect()
    first.add("shared")
    assert second.contains("shared")
    root.setAttribute("class", "reset")
    assert stored.view.contains("reset")
    change(None)
    change(views[2])
    gc_collect()
    assert views[2].contains("panel")
    assert views[2].contains("later")
    return str(first.length) + str(second.length) + str(views[2].length)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("body", [
    'def getAttribute(self, name: str) -> str | None: return "override"',
    'def setAttribute(self, name: str, value: str) -> None: pass',
    'def _is_observed_attribute(self, name: str) -> bool: return name == "class"',
])
@pytest.mark.parametrize("opaque", [False, True])
def test_class_views_reject_callbacks_before_losing_wrapper_dispatch(body, opaque):
    with pytest.raises(LLVMUnsupported, match="DOM attribute overrides|observed-attribute callbacks"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    {body}
def main() -> int:
    root{": Element" if opaque else ""} = Panel()
    return root.classList.length
''')


@pytest.mark.parametrize("operation", [
    'DOMTokenList()', 'div().classList.toggle("x")',
    'div().classList != "text"',
])
def test_unported_token_surface_fails_at_compile_time(operation):
    with pytest.raises((CompilationError, LLVMUnsupported)):
        transpile_llvm(f'''
from pyjs.web.dom import DOMTokenList
from pyjs.web.domx import div
def main() -> int:
    {operation}
    return 0
''')


@pytest.mark.parametrize("body", ["pass", "def __init__(self): self.label = 1"])
def test_token_subclasses_fail_before_emitting_an_invalid_native_layout(body):
    with pytest.raises(LLVMUnsupported, match="DOMTokenList subclasses are not supported"):
        transpile_llvm(f'''
from pyjs.web.dom import DOMTokenList
class Tokens(DOMTokenList):
    {body}
class Child(Tokens):
    pass
def main() -> int:
    return Child().length
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_class_token_length_without_token_method_calls(tmp_path, optimize):
    LLVM().assert_matches_python(r'''
        from pyjs.web.domx import div

        def main() -> int:
            return div({"class": "one\u2003two two"}).classList.length
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_class_token_queries_are_live_and_preserve_whitespace(tmp_path, optimize):
    LLVM().assert_matches_python(r'''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import div
        from pyjs.web.ssr import render_html
        from pyjs.web.domx import CustomElement

        class Panel(CustomElement):
            def __init__(self):
                self.classList.add("custom", "panel")

        def change(root: Element) -> str:
            root.setAttribute("class", "changed\u2003twice twice")
            gc_collect()
            return "changed"

        def main() -> str:
            gc_set_threshold(1)
            root = div({"class": "  α\tβ\u2003α\x00x  "}, "child")
            view = root.classList
            result = str(view.length)
            for token in ["α", "β", "α\x00x", "", "α β", "x", "α\x00"]:
                result += str(view.contains(token))
            result += render_html(root)
            result += str(view.contains(token=change(root)))
            result += str(view.length)
            root.classList.remove("twice")
            result += str(view.length) + str(view.contains("twice"))
            root.removeAttribute("class")
            result += str(view.length) + str(view.contains("changed"))
            root.setAttribute("class", "\u2003\t\r\n ")
            result += str(view.length) + str(view.contains(""))
            panel = Panel()
            result += str(panel.classList.length) + str(panel.classList.contains("custom"))
            gc_collect()
            return result + render_html(root)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_class_token_queries_do_not_allocate(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from pyjs.web.domx import div
        from tests.native.allocation_support import arm, remaining

        def main() -> int:
            root = div({{"class": "one two one"}})
            view = root.classList
            {'gc_collect()' if managed else 'pass'}
            index = 0
            arm(1)
            while index < 128:
                if view.length != 3 or not view.contains("one"):
                    return 1
                if view.contains("two one") or view.contains(""):
                    return 2
                index += 1
            if remaining() != 1:
                return 3
            arm(0)
            return 0
    ''')
    assert ("define ptr @pyjs.gc.new()" in source) == managed
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("values", ['[1]', '("valid", 1)'])
def test_starred_class_tokens_reject_nonstring_items(values):
    with pytest.raises((CompilationError, LLVMUnsupported), match="requires its declared type and storage; use an explicit conversion|cannot bind parameter 'tokens'"):
        transpile_llvm(f'''
            from pyjs.web.domx import div

            def main() -> int:
                div().classList.add(*{values})
                return 0
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_starred_class_tokens_preserve_sources_order_and_raising_generators(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import div
        from pyjs.web.ssr import render_html

        def observe(root: Element, events: list[str], value: str) -> str:
            events.append(render_html(root))
            gc_collect()
            return value + "!"

        def tokens(root: Element, events: list[str], fail: bool) -> Iterator[str]:
            yield observe(root, events, "generated")
            if fail:
                raise ValueError("failed token")
            yield observe(root, events, "last")

        def forward(root: Element, *values: str) -> None:
            root.classList.add(*values)

        def main() -> str:
            gc_set_threshold(1)
            root = div({"class": "old old"}, "kept")
            events: list[str] = []
            source = ["a b", "a", "", "a b"]
            root.classList.add("first", *source, observe(root, events, "after"))
            result = render_html(root)
            root.classList.remove(*("old", "old"), "missing")
            result += render_html(root)
            empty: list[str] = []
            root.classList.add(*empty)
            root.classList.remove(*())
            forward(root, "forward", "tail")
            root.classList.add(*tokens(root, events, False))
            result += render_html(root)
            before = render_html(root)
            try:
                root.classList.add("unpublished", *tokens(root, events, True), "unreached")
            except ValueError:
                result += "caught" if render_html(root) == before else "changed"
            root.classList.remove(*["generated!", "last!"], *source)
            gc_collect()
            return result + render_html(root) + str(events) + str(source)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_class_token_batches_match_python_whitespace_and_duplicates(tmp_path, optimize):
    LLVM().assert_matches_python(r'''
        from pyjs.native import gc_collect
        from pyjs.web.domx import div, span, tag
        from pyjs.web.ssr import render_html

        def siblings(*values: dict[str, str] | str) -> str:
            first = div(*values)
            second = div(*values)
            first.classList.add("new", "new", "last")
            gc_collect()
            return render_html(first) + render_html(second)

        def main() -> str:
            root = div({"title": "kept", "class": "  α\tβ\u2003α  "}, span("child"))
            root.classList.add("α", "β")
            root.classList.remove("missing", "")
            result = render_html(root)
            root.classList.remove("α", "missing")
            result += render_html(root)
            root.classList.remove("α", "α", "β")
            result += render_html(root)
            root.classList.add("a b", "a", "", "", "b", "a b")
            gc_collect()
            result += render_html(root)
            root.classList.remove("a", "a", "b", "")
            result += render_html(root)
            root.classList.add()
            root.classList.remove()
            result += render_html(root)
            tag(root, {"class": "old old"}, {"class": "x x x"})
            root.classList.remove("x", "x")
            result += render_html(root)
            result += siblings({"class": "shared shared"}, "child")
            empty = div("empty")
            empty.classList.remove("absent")
            result += render_html(empty)
            empty.classList.add("")
            result += render_html(empty)
            return result
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["inferred", "explicit-gc"])
def test_class_token_allocation_failures_leave_the_entire_batch_unpublished(tmp_path, optimize, managed):
    limiter = shutil.which("prlimit")
    if limiter is None:
        pytest.skip("requires Linux prlimit for bounded native failure execution")
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from pyjs.web.dom import Element
        from pyjs.web.domx import div
        from pyjs.web.ssr import render_html
        from tests.native.allocation_support import arm, remaining

        def change(root: Element, mode: int) -> None:
            if mode == 0:
                root.classList.add("new", "a b", "a", "", "last")
            elif mode == 4:
                root.classList.add(*("new", "a b"), "a", *("", "last"))
            elif mode == 5:
                root.classList.add(*["new", "a b"], "a", *["", "last"])
            elif mode == 1 or mode == 3:
                root.classList.remove("old", "old", "absent", "other")
            else:
                root.classList.add("old", "other")

        def main() -> int:
            for mode in range(6):
                for width in (0, 7, 20):
                    stages = 1
                    failure = 0
                    while failure <= stages:
                        root = div("kept child")
                        for index in range(width):
                            root.setAttribute("data-" + str(index), "kept")
                        if mode in (1, 2, 3):
                            root.setAttribute("class", "  old other old  ")
                        if mode == 3:
                            root.setAttribute("class", "old " * 20 + "other")
                        before = render_html(root)
                        caught = False
                        arm(1000 if failure == 0 else failure)
                        try:
                            change(root, mode)
                        except MemoryError:
                            caught = True
                        if failure == 0:
                            stages = 1000 - remaining()
                        arm(0)
                        {'gc_collect()' if managed else 'pass'}
                        if caught != (failure != 0):
                            return 1
                        if stages < 2:
                            return 2
                        if caught:
                            if render_html(root) != before:
                                return 3
                            change(root, mode)
                        expected = "" if mode in (1, 2, 3) else "new a b a  last"
                        if mode == 2:
                            expected = "  old other old  "
                        if mode == 3:
                            expected = "old " * 17 + "old"
                        if root.getAttribute("class") != expected:
                            return 4
                        failure += 1
                    if mode == 0 and width == 0:
                        for repeat in range(1024):
                            root.removeAttribute("class")
                            arm(stages)
                            try:
                                change(root, mode)
                                return 5
                            except MemoryError:
                                pass
                            arm(0)
                            {'gc_collect()' if managed else 'pass'}
                        change(root, mode)
                        if root.getAttribute("class") != "new a b a  last":
                            return 6
                    if mode == 2:
                        for repeat in range(1024):
                            change(root, mode)
            return 0
    ''')
    # The shared expanded-call binder may infer managed packs even without an
    # explicit gc_collect(). Injection discovers the allocator actually emitted.
    if managed:
        assert "define ptr @pyjs.gc.new()" in source
    executable = LLVM().compile(_fail_allocations(source, managed), tmp_path, optimize=optimize)
    # Each scratch arena reserves at least 64 KiB. Repeated failures and
    # unchanged batches must release it to fit within this process limit.
    result = subprocess.run(
        [limiter, "--as=33554432", "--core=0", executable],
        capture_output=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
