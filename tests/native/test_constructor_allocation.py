"""Construction publishes only after storage, initialization and effects succeed."""

import pytest

from pyjs.native.llvm import transpile_llvm
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("collect", [False, True])
def test_object_storage_failure_precedes_initialization_and_keeps_assignment(tmp_path, optimize, collect):
    source = transpile_llvm(f'''
        from dataclasses import dataclass, replace
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining

        class Counter:
            def __init__(self):
                self.entered = 0

        class Record:
            def __init__(self, counter: Counter, label: str):
                counter.entered += 1
                self.label = label
            def size(self) -> int:
                return len(self.label)

        class Derived(Record):
            def size(self) -> int:
                return len(self.label) + 1

        @dataclass
        class Data:
            counter: Counter
            label: str
            def __post_init__(self) -> None:
                self.counter.entered += 1

        class Empty:
            pass

        def main() -> int:
            {"gc_set_threshold(1)" if collect else "pass"}
            counter = Counter()
            saved_record = Record(counter, "old")
            saved_data = Data(counter, "old")
            saved_empty = Empty()
            for mode in range(5):
                failure = 0
                stages = 1
                while failure <= stages:
                    record, data, empty = saved_record, saved_data, saved_empty
                    counter.entered = 0
                    caught = False
                    arm(1000 if failure == 0 else failure)
                    try:
                        if mode == 0:
                            record = Record(counter, "new")
                        elif mode == 1:
                            record = Derived(counter, "new")
                        elif mode == 2:
                            data = Data(counter, "new")
                        elif mode == 3:
                            empty = Empty()
                        else:
                            data = replace(saved_data, label="new")
                    except MemoryError:
                        caught = True
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    {"gc_collect()" if collect else "pass"}
                    assert stages > 0 and caught == (failure != 0)
                    assert counter.entered == (0 if caught or mode == 3 else 1)
                    if caught:
                        assert record is saved_record and data is saved_data and empty is saved_empty
                    elif mode < 2:
                        assert record.size() == (3 if mode == 0 else 4)
                    elif mode == 3:
                        assert empty is not saved_empty
                    else:
                        assert data.label == "new"
                    assert saved_record.label == "old" and saved_data.label == "old"
                    assert Derived(counter, "retry").size() == 6
                    assert replace(saved_data, label="retry").label == "retry"
                    failure += 1
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=collect, optimize=optimize)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("collect", [False, True])
def test_custom_assembly_failure_defers_effects_and_identity_can_retry(tmp_path, optimize, collect):
    source = transpile_llvm(f'''
        from pyjs import effect, state
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import CustomElement
        from pyjs.web.ssr import render_html
        from tests.native.allocation_support import arm, remaining

        class Counter:
            def __init__(self):
                self.entered = 0
                self.finished = 0
                self.effects = 0
                self.stages = 0
                self.caught = 0

        class Panel(CustomElement):
            title = state("ready")
            enabled = state(True)
            hidden = state(False)
            count = state(-9223372036854775808)
            ratio = state(-0.0)

            def __init__(self, counter: Counter, retry: int = -1):
                self.counter = counter
                counter.entered += 1
                if retry < 0:
                    super().__init__()
                else:
                    arm(1000 if retry == 0 else retry)
                    try:
                        super().__init__()
                    except MemoryError:
                        arm(0)
                        counter.caught += 1
                        {"gc_collect()" if collect else "pass"}
                        super().__init__()
                    if retry == 0:
                        counter.stages = 1000 - remaining()
                    arm(0)
                    super().__init__()
                self.append("body")
                counter.finished += 1

            @effect(title, enabled)
            def observe(self):
                self.counter.effects += 1

        def check(panel: Panel) -> None:
            assert panel.getAttribute("title") == "ready"
            assert panel.getAttribute("enabled") == "" and not panel.hasAttribute("hidden")
            assert panel.getAttribute("count") == "-9223372036854775808"
            assert panel.getAttribute("ratio") == "-0.0"
            html = render_html(panel)
            assert ">body</" in html and html.count('data-self-id="') == 1

        def main() -> int:
            {"gc_set_threshold(1)" if collect else "pass"}
            counter = Counter()
            saved = Panel(counter)
            expected = render_html(saved)
            failure, stages = 0, 1
            while failure <= stages:
                counter.entered = 0
                counter.finished = 0
                counter.effects = 0
                result = saved
                caught = False
                arm(1000 if failure == 0 else failure)
                try:
                    result = Panel(counter)
                except MemoryError:
                    caught = True
                if failure == 0:
                    stages = 1000 - remaining()
                arm(0)
                {"gc_collect()" if collect else "pass"}
                assert stages > 0 and caught == (failure != 0)
                if caught:
                    assert result is saved and counter.effects == 0
                    if failure == 1:
                        assert counter.entered == 0
                else:
                    assert counter.entered == counter.finished == counter.effects == 1
                    check(result)
                assert render_html(saved) == expected
                check(Panel(counter))
                failure += 1
            check(Panel(counter, 0))
            assert counter.stages > 0
            for failure in range(1, counter.stages + 1):
                panel = Panel(counter, failure)
                {"gc_collect()" if collect else "pass"}
                check(panel)
                assert counter.caught == failure
                assert panel.getAttribute("data-self-id") != saved.getAttribute("data-self-id")
                assert render_html(saved) == expected
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=collect, optimize=optimize)
    assert result.stdout == result.stderr == b""
