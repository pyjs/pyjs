"""Static namespaces do not become runtime locals during operand expansion."""

from textwrap import dedent

import pytest

from pyjs.analysis.rendering import TypeWriter
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.tooling.llvm import LLVM


class QualifiedReceiver:
    @staticmethod
    def render(value: int) -> str:
        return str(value)


@pytest.mark.parametrize("optimize", [0, 2])
def test_module_qualified_class_stays_static_and_function_values_stay_callable(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        import tests.native.test_module_operands as fixtures

        def invoke(function: Callable[[int], str], value: int) -> str:
            return function(value)

        def main() -> str:
            result = ""
            for flag in (False, True):
                result += fixtures.QualifiedReceiver.render(1 if flag else 2)
                result += invoke(fixtures.QualifiedReceiver.render, 3 if flag else 4)
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


def test_module_namespace_remains_static_across_conditional_blocks():
    with analyze_source('''
        import math
        def main() -> int:
            n = 1
            return math.floor(1.5 if n else 2.5)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        actual = "\n".join(TypeWriter().visit(block) for block in analysis.entry_point.ir.blocks)
    assert actual == dedent('''
        block entry:
            n: int = 1
            branch n.[int]__bool__():
                true -> conditional_true
                false -> conditional_false
        block conditional_true:
            jump conditional_done(1.5)
        block conditional_false:
            jump conditional_done(2.5)
        block conditional_done(conditional_done_value: float):
            return math.floor(float(conditional_done_value))
    ''').strip()


@pytest.mark.parametrize("optimize", [0, 2])
def test_module_call_conditionals_and_expansions_keep_argument_order(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import json
        import math as numbers

        EVENTS: list[str] = []

        def value(name: str, fail: bool) -> int:
            EVENTS.append(name)
            if fail:
                raise ValueError(name)
            return 2

        def main() -> str:
            output = ""
            for pretty in (False, True):
                for fail in (False, True, False):
                    try:
                        output += json.dumps(
                            [value("input", False)],
                            indent=value("indent", fail) if pretty else None,
                            separators=(",", ":") if value("separators", False) else None,
                            ensure_ascii=True if pretty else False,
                        )
                    except ValueError as error:
                        output += "caught:" + str(error)
                output += str(numbers.floor(1.5 if pretty else 2.5))
                output += json.dumps(1 if pretty else 2)
                output += json.dumps([*[value("expanded", False)], 3])
            return output + "|" + str(EVENTS)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_instance_receiver_is_still_saved_before_conditional_mutates_it(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        class Receiver:
            def __init__(self, prefix: str):
                self.prefix = prefix
            def render(self, value: int) -> str:
                return self.prefix + str(value)

        CURRENT: list[Receiver] = []
        EVENTS: list[str] = []

        def receiver() -> Receiver:
            EVENTS.append("receiver")
            return CURRENT[0]

        def replace() -> bool:
            EVENTS.append("replace")
            CURRENT[0] = Receiver("second")
            return True

        def main() -> str:
            CURRENT.append(Receiver("first"))
            result = receiver().render(1 if replace() else 2)
            result += CURRENT[0].render(3)
            return result + str(EVENTS)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr
