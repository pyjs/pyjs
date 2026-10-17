import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_dom_arguments_follow_each_python_api(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import Document, gc_collect
        from pyjs.native import div as native_div
        from pyjs.web.dom import Element
        from pyjs.web.domx import div, span, tag
        from pyjs.web.ssr import render_html

        def forwarded(*values) -> Element:
            return div(*values)

        def observe(events: list[int]) -> str:
            events.append(1)
            gc_collect()
            return "after"

        def main() -> str:
            result = ""
            child: Element = span("child")
            strings: list[str | None] = ["first", None, "last"]
            elements: list[Element | None] = [child, None, child]
            mixed: list[str | Element | None] = ["first", child, None, "last"]
            document = Document()
            for mode in range(9):
                events: list[int] = []
                target = div("old")
                caught = False
                try:
                    if mode == 0:
                        target = div(*strings, observe(events))
                    elif mode == 1:
                        target = div(*elements, observe(events))
                    elif mode == 2:
                        target = forwarded(*mixed, observe(events))
                    elif mode == 3:
                        tag(target, *mixed, observe(events))
                    elif mode == 4:
                        target.append(*strings, *elements, *mixed, observe(events))
                    elif mode == 5:
                        target.replaceChildren(*strings, *elements, *mixed, observe(events))
                    elif mode == 6:
                        native_div(document, *strings, observe(events))
                    elif mode == 7:
                        target = div(*(None, "last"), observe(events))
                    else:
                        tag(target, *(child, None, "last"), observe(events))
                except TypeError:
                    caught = True
                gc_collect()
                if len(events) != 1:
                    return "argument not evaluated"
                if caught != (mode < 4 or mode >= 6):
                    return "wrong exception"
                result += render_html(target)
                target.append("retry")
                result += render_html(target)
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_expanded_builtin_replacement_checks_each_virtual_append(tmp_path, optimize):
    # The builtin ignores None, but a typed override must reject it before
    # entering the body. The preceding child remains visible after failure.
    source = '''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.calls = 0
    def append(self, *children: Element | str) -> None:
        self.calls += 1
        gc_collect()
        super().append(*children)
def later(events: list[int]) -> str:
    events.append(1)
    gc_collect()
    return "tail"
def main() -> int:
    gc_set_threshold(1)
    panel = Panel()
    values: list[str | None | dict[str, str]] = ["first", None, {"title": "ignored"}]
    events: list[int] = []
    try:
        panel.replaceChildren(*values, later(events))
    except TypeError:
        pass
    else:
        return 1
    assert panel.calls == 1
    assert events == [1]
    assert panel.textContent == "first"
    values[:] = ["retry"]
    panel.replaceChildren(*values, later(events))
    assert panel.calls == 3
    assert panel.textContent == "retrytail"
    return 0
'''
    executable = LLVM().compile(transpile_llvm(source), tmp_path, optimize=optimize,
                                sanitizers=("address", "undefined"))
    result = subprocess.run([executable], capture_output=True, timeout=15)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_starred_text_and_union_allocation_failures_preserve_the_dom(
    tmp_path, optimize, managed,
):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from pyjs.web.dom import Element
        from pyjs.web.domx import div, span
        from pyjs.web.ssr import render_html
        from tests.native.allocation_support import arm, remaining

        def main() -> int:
            texts = ["<&>", "one", "two", "three", "four"]
            child: Element = span("child")
            mixed: list[str | Element | dict[str, str]] = [
                "<&>", child, {{"title": "attributes"}}, child, "end",
            ]
            saved = div("saved")
            for mode in range(4):
                failure = 0
                stages = 1
                expected = ""
                while failure <= stages:
                    result = saved
                    target = div("saved")
                    caught = False
                    arm(1000 if failure == 0 else failure)
                    try:
                        if mode == 0:
                            result = div(*texts)
                        elif mode == 1:
                            result = div(*mixed)
                        elif mode == 2:
                            target.append(*texts)
                            result = target
                        else:
                            target.replaceChildren(*mixed)
                            result = target
                    except MemoryError:
                        caught = True
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    {'gc_collect()' if managed else 'pass'}
                    if stages < 2 or caught != (failure != 0):
                        return 1
                    if caught:
                        if result is not saved or render_html(target) != "<div>saved</div>":
                            return 2
                    else:
                        expected = render_html(result)
                    retry = div("saved")
                    if mode == 0:
                        retry = div(*texts)
                    elif mode == 1:
                        retry = div(*mixed)
                    elif mode == 2:
                        retry.append(*texts)
                    else:
                        retry.replaceChildren(*mixed)
                    if render_html(retry) != expected:
                        return 3
                    if render_html(child) != "<span>child</span>" or len(mixed) != 5:
                        return 4
                    failure += 1
            return 0
    ''')
    assert ("define ptr @pyjs.gc.new()" in source) == managed
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)



@pytest.mark.parametrize("optimize", [0, 2])
def test_attribute_mapping_unions_keep_builder_and_mutation_semantics(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from typing import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import CustomElement, div, tag, tw
        from pyjs.web.ssr import render_html

        class Badge(CustomElement):
            def __init__(self):
                super().__init__()
                self.append("badge")

        def generated(values: list[str | dict[str, str] | Badge]) -> Iterator[str | dict[str, str] | Badge]:
            for value in values:
                gc_collect()
                yield value

        def forwarded(*values) -> str:
            return render_html(div(*values))

        def main() -> str:
            gc_set_threshold(1)
            attrs = {"title": '<safe> & "quoted"', "data-other": "first"}
            values: list[str | dict[str, str] | Badge] = ["before", attrs, Badge(), tw("active"), "after"]
            built = div(*values)
            result = render_html(built)
            result += forwarded(*generated(values))
            target = div({"title": "kept"}, "old")
            target.append(*values)
            gc_collect()
            result += render_html(target)
            target.replaceChildren(*generated(values))
            result += render_html(target)
            tag(target, *values)
            result += render_html(target)
            attrs["title"] = "changed"
            gc_collect()
            result += render_html(built) + render_html(div(*values))
            nullable: list[dict[str, str] | None] = [attrs, None]
            target.replaceChildren(*nullable)
            result += render_html(target)
            try:
                tag(target, *nullable)
            except TypeError:
                result += render_html(target)
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))

    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_child_mutations_preserve_reused_forwarding_pack_and_failed_operands(tmp_path, optimize):
    # Preserve the old dom_nullable forwarding scenario. Shared DOM signatures
    # reject direct mapping children; an expanded pack retains its runtime kinds.
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement, div, span, tag, tw
        from pyjs.web.ssr import render_html

        class Forwarded(CustomElement):
            def __init__(self, *children):
                super().__init__()
                self.append(*children)

        def apply(target: Element, mode: int, *values) -> str:
            if mode == 0:
                target.append(*values)
            elif mode == 1:
                target.replaceChildren(*values)
            else:
                tag(target, *values)
            gc_collect()
            return render_html(target) + render_html(div(*values))

        def observe(target: Element, events: list[str], fail: bool) -> dict[str, str]:
            events.append(render_html(target))
            gc_collect()
            if fail:
                raise ValueError("argument failed")
            return {"title": "new", "data-extra": "ignored by mutations"}

        def main() -> str:
            gc_set_threshold(1)
            result = ""
            events: list[str] = []
            for mode in range(3):
                target = div({"title": "old", "class": "saved"}, "old")
                values = ({"title": "new"}, tw("changed"), span("<child>"), "end")
                result += apply(target, mode, *values)
                result += render_html(Forwarded(*values))
                target = div({"title": "old"}, "unchanged")
                try:
                    apply(target, mode, "first", observe(target, events, True))
                except ValueError:
                    result += render_html(target)
                result += apply(target, mode, "last", observe(target, events, False))
            target = div({"title": "kept"}, "discarded")
            mappings = ({"title": "ignored"}, tw("ignored"))
            target.replaceChildren(*mappings)
            result += render_html(target)
            target.append(*mappings)
            return result + render_html(target) + str(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
