from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import BOOLEAN_NUMERIC_CONTRACT

ARITHMETIC = (
    ("add", "+"), ("subtract", "-"), ("multiply", "*"),
    ("divide", "/"), ("floor_divide", "//"), ("modulo", "%"),
    ("equal", "=="), ("unequal", "!="), ("less", "<"),
    ("less_equal", "<="), ("greater", ">"), ("greater_equal", ">="),
)
BITWISE = (("and_bits", "&"), ("or_bits", "|"), ("xor_bits", "^"),
           ("left_shift", "<<"), ("right_shift", ">>"))
VALUES = {"bool": "[False, True]", "int": "[-3, 0, 2]", "float": "[-2.5, 0.0, 1.5]"}


@pytest.mark.parametrize("operator", ["and", "or"])
@pytest.mark.parametrize("deferred", ["lambda: EXPR", "(EXPR for _ in range(2))"])
def test_deferred_selection_requires_fresh_subtype_proof(operator, deferred):
    expression = deferred.replace("EXPR", f"(value {operator} Action()).only()")
    with pytest.raises(CompilationError, match="Attribute 'only' is not defined on every member"):
        transpile_llvm(dedent(f'''
            class Base: pass
            class Action(Base):
                def only(self) -> str: return "only"
            def main() -> str:
                value: Base = Action()
                assert isinstance(value, Action)
                query = {expression}
                return str({"query()" if deferred.startswith("lambda") else "list(query)"})
        '''))


@pytest.mark.parametrize("optimize", [0, 2])
def test_deferred_selection_with_fresh_subtype_proof(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        class Base: pass
        class Action(Base):
            def only(self) -> str: return "only"
        def main() -> str:
            value: Base = Action()
            query = lambda: (value or Action()).only() if isinstance(value, Action) else "base"
            items = ((value and value).only() if isinstance(value, Action) else "base"
                     for _ in range(3))
            first = (query(), next(items))
            value = Base()
            second = (query(), next(items))
            value = Action()
            return repr((first, second, query(), next(items)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_boolean_contract(tmp_path, optimize):
    result = LLVM().assert_matches_python(
        BOOLEAN_NUMERIC_CONTRACT.source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.returncode == 0, BOOLEAN_NUMERIC_CONTRACT.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("left_type,right_type", [
    ("bool", "bool"), ("bool", "int"), ("int", "bool"),
    ("bool", "float"), ("float", "bool"),
])
def test_boolean_scalar_operator_matrix(tmp_path, optimize, left_type, right_type):
    operations = ARITHMETIC + (BITWISE if "float" not in (left_type, right_type) else ())
    # One compilation per typed pair, with named functions and labelled output
    # so individual operators remain easy to locate in a differential failure.
    source = ""
    for name, operator in operations:
        source += dedent(f'''
            def {name}(left: {left_type}, right: {right_type}) -> str:
                try:
                    return repr(left {operator} right)
                except ZeroDivisionError:
                    return "zero division"
                except ValueError:
                    return "invalid shift"
        ''')
    calls = ", ".join(f'"{name}:" + {name}(left, right)' for name, _ in operations)
    source += dedent(f'''
        def main() -> str:
            rows: list[str] = []
            for left in {VALUES[left_type]}:
                for right in {VALUES[right_type]}:
                    rows.append(repr((left, right)) + ":" + "|".join([{calls}]))
            return ";".join(rows)
    ''')
    comparison = LLVM().assert_matches_python(
        source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_reflected_numeric_operand_effects_and_failures(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import operator

        def integer(events: list[str], fail: bool) -> int:
            events.append("int")
            if fail:
                raise ValueError("integer failed")
            return 2

        def floating(events: list[str], fail: bool) -> float:
            events.append("float")
            if fail:
                raise ValueError("float failed")
            return 1.5

        def main() -> str:
            events: list[str] = []
            values: list[float] = []
            for fail_left in [False, True]:
                for fail_right in [False, True]:
                    try:
                        values.append(integer(events, fail_left) - floating(events, fail_right))
                    except ValueError as error:
                        events.append(str(error))
            values.append(operator.sub(integer(events, False), floating(events, False)))
            values.append(floating(events, False).__rsub__(integer(events, False)))
            compared = integer(events, False) < floating(events, False)
            return repr((values, compared, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_boolean_operator_consumers_and_result_identity(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import operator

        def boolean(value: bool, label: str, events: list[str]) -> bool:
            events.append(label)
            return value

        def integer(value: int, label: str, events: list[str]) -> int:
            events.append(label)
            return value

        def floating(value: float, label: str, events: list[str]) -> float:
            events.append(label)
            return value

        def main() -> str:
            events: list[str] = []
            first = boolean(True, "a", events) + integer(2, "b", events)
            second = boolean(True, "c", events) - floating(1.5, "d", events)
            third = integer(2, "e", events) ^ boolean(True, "f", events)
            bits = operator.and_(True, True)
            total = operator.add(True, True)
            values = [10, 20, 30, 40]
            start = True + False
            stop = True + True
            return repr((first, second, third, "".join(events), bits, total,
                         type(bits) is bool, type(total) is int,
                         values[start:stop], "abcd"[start:stop],
                         True.__add__(True), True.__rsub__(2), False.__rand__(True),
                         True.__xor__(False), True ** False, False ** False,
                         True ** 3, 2 ** True, True << True, operator.or_(False, True)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
