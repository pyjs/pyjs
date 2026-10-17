import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_token_and_child_keyword_packs_follow_python_binding(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.domx import div
from pyjs.web.ssr import render_html
def main() -> str:
    root = div({"class": "a"})
    view = root.classList
    options = {"token": "a"}
    empty: dict[str, str] = {}
    assert view.contains(**options)
    view.add("b", **empty)
    root.append("child", **empty)
    root.append(**empty)
    before = render_html(root)
    rejected = 0
    try:
        view.contains("a", **options)
    except TypeError:
        rejected += 1
    try:
        view.add(**options)
    except TypeError:
        rejected += 1
    try:
        root.append("unpublished", **options)
    except TypeError:
        rejected += 1
    gc_collect()
    assert rejected == 3
    assert render_html(root) == before
    return before
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_dom_attribute_arguments_share_python_binding_and_evaluation_order(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from typing import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import CustomElement
        from pyjs.web.ssr import render_html

        class Panel(CustomElement):
            def setAttribute(self, name: str, value: str) -> None:
                super().setAttribute(value="custom:" + value, name=name)

        class Plain(CustomElement):
            pass

        def text(events: list[str], value: str) -> str:
            events.append(value)
            gc_collect()
            return value

        def values(events: list[str], count: int) -> Iterator[str]:
            for value in ["data-test", "expanded", "extra"][:count]:
                yield text(events, value)

        def owner(value: Plain | Panel, events: list[str]) -> Plain | Panel:
            events.append("owner")
            gc_collect()
            return value

        def update(value: Plain | Panel) -> str:
            events: list[str] = []
            owner(value, events).setAttribute(
                value=text(events, "named<&"), name=text(events, "data-test"))
            result = str(value.getAttribute(name="data-test"))
            pair = ("data-test", "tuple")
            value.setAttribute(*pair)
            result += str(value.getAttribute(*("data-test",)))
            options = {"value": "mapped", "name": "data-test"}
            value.setAttribute(**options)
            result += str(value.hasAttribute(**{"name": "data-test"}))
            empty: dict[str, str] = {}
            for count in [0, 1, 2, 3]:
                before = render_html(value)
                try:
                    value.setAttribute(*values(events, count), **empty)
                    result += render_html(value)
                except TypeError:
                    result += "arity:" + str(before == render_html(value))
                gc_collect()
            try:
                value.setAttribute(*values(events, 1),
                    value=text(events, "keyword"))
                result += render_html(value)
            except TypeError:
                result += "unexpected"
            names = {"name": "data-test"}
            try:
                value.setAttribute("positional", **names,
                    value=text(events, "after-conflict"))
            except TypeError:
                result += "conflict"
            try:
                value.setAttribute(value=text(events, "duplicate"), **options,
                    name=text(events, "must-not-run"))
            except TypeError:
                result += "duplicate"
            for rejected in [empty, {"unexpected": "name"}]:
                before = render_html(value)
                try:
                    value.getAttribute(**rejected)
                except TypeError:
                    result += "invalid:" + str(before == render_html(value))
            value.removeAttribute(**{"name": "data-test"})
            result += str(value.getAttribute(name="data-test"))
            value.setAttribute(**options)
            return result + render_html(value) + str(events) + str(options)

        def direct() -> str:
            value = Plain()
            value.setAttribute(value="direct<&", name="data-test")
            result = str(value.getAttribute(**{"name": "data-test"}))
            result += str(value.hasAttribute(*["data-test"]))
            value.removeAttribute(name="data-test")
            result += str(value.querySelector(selector="ignored") is value)
            data = Plain()
            data.set_data(value="before", name="café")
            options = {"name": "café", "value": "after<&"}
            data.set_data(**options)
            result += str(data.get_data(*("café",)))
            return result + render_html(data)

        def main() -> str:
            gc_set_threshold(1)
            return direct() + update(Plain()) + update(Panel())
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_dom_argument_and_data_allocations_fail_before_mutation_and_allow_retry(tmp_path, managed):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from pyjs.web.domx import CustomElement
        from pyjs.web.ssr import render_html
        from tests.native.allocation_support import arm, remaining

        class Panel(CustomElement):
            pass

        def operation(value: Panel, options: dict[str, str], mode: int) -> None:
            if mode == 0:
                value.getAttribute(**options)
            elif mode == 1:
                value.setAttribute(**options)
            elif mode == 2:
                value.get_data(**options)
            elif mode == 3:
                value.set_data(**options)
            elif mode == 4:
                value.hasAttribute(**options)
            elif mode == 5:
                value.removeAttribute(**options)
            else:
                value.querySelector(**options)

        def main() -> int:
            for mode in range(7):
                stages = 1
                failure = 0
                while failure <= stages:
                    value = Panel()
                    value.setAttribute("test", "before")
                    value.set_data("test", "before")
                    options = {{"selector" if mode == 6 else "name": "test"}}
                    if mode == 1 or mode == 3:
                        options["value"] = "after<&"
                    before = render_html(value)
                    caught = False
                    arm(1000 if failure == 0 else failure)
                    try:
                        operation(value, options, mode)
                    except MemoryError:
                        caught = True
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    {'gc_collect()' if managed else 'pass'}
                    if stages < 1 or caught != (failure != 0):
                        print((mode, failure, stages, caught))
                        return 1
                    if caught and render_html(value) != before:
                        return 2
                    operation(value, options, mode)
                    if mode == 1 and value.getAttribute("test") != "after<&":
                        return 3
                    if mode == 3 and value.get_data("test") != "after<&":
                        return 4
                    failure += 1
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=2)


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapped_dom_receiver_survives_collecting_keyword_callbacks(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import span

        class Holder:
            def __init__(self, value: Element):
                self.value = value

        def options(holder: Holder, fail: bool) -> dict[str, str]:
            holder.value = span("replacement")
            gc_collect()
            if fail:
                raise ValueError("argument failed")
            return {"name": "data-test"}

        def read(holder: Holder, fail: bool) -> str:
            try:
                return str(holder.value.getAttribute(**options(holder, fail)))
            except ValueError:
                gc_collect()
                return "caught"

        def make() -> Holder:
            value = span("original")
            value.setAttribute("data-test", "saved")
            return Holder(value)

        def main() -> str:
            gc_set_threshold(1)
            result = read(make(), False) + read(make(), True)
            gc_collect()
            return result + read(make(), False)
    '''
    result = LLVM().assert_matches_python(
        source, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
