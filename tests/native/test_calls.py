import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import KEYWORD_ARGUMENT_CONTRACT


def test_shared_keyword_argument_contract(tmp_path):
    result = LLVM().assert_matches_python(KEYWORD_ARGUMENT_CONTRACT.source, directory=tmp_path)
    assert result.native.returncode == 0, KEYWORD_ARGUMENT_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("invocation", ["forward(value)", "forward(value=value)"])
@pytest.mark.parametrize("kind, value", [
    ("tuple[int, ...]", "(9, 3, 4)"),
    ("list[tuple[int, ...]]", "[(9, 3, 4)]"),
    ("dict[str, tuple[int, ...]]", "{'a': (9, 3, 4)}"),
])
def test_forwarding_inline_preserves_tuple_views(invocation, kind, value):
    LLVM().assert_matches_python(f'''
        from pyjs import llvm

        @llvm.inline("{{value}}")
        def forward(value: {kind}) -> {kind}:
            return value

        def main() -> int:
            value = {value}
            result = {invocation}
            assert result is value
            return len(result)
        ''')


@pytest.mark.parametrize("invocation", ["forward(value)", "forward(value=value)"])
@pytest.mark.parametrize("reverse", [False, True], ids=["fixed-to-variable", "variable-to-fixed"])
@pytest.mark.parametrize("container, value", [
    ("{}", "pack(9, 3, 4)"),
    ("list[{}]", "[pack(9, 3, 4)]"),
    ("dict[str, {}]", "{'a': pack(9, 3, 4)}"),
])
def test_forwarding_inline_preserves_return_tuple_views(invocation, reverse, container, value):
    source_type = container.format("tuple[int, ...]" if reverse else "tuple[int, int, int]")
    result_type = container.format("tuple[int, int, int]" if reverse else "tuple[int, ...]")
    if not reverse:
        value = value.replace("pack(9, 3, 4)", "(9, 3, 4)")
    LLVM().assert_matches_python(f'''
        from pyjs import llvm

        @llvm.inline("{{value}}")
        def forward(value: {source_type}) -> {result_type}:
            return value

        def pack(*values: int) -> tuple[int, ...]:
            return values

        def main() -> int:
            value = {value}
            result = {invocation}
            assert result is value
            return len(result)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_forwarding_inline_preserves_matching_layouts_and_numeric_conversion(optimize):
    LLVM().assert_matches_python('''
    from pyjs import llvm, int8, float32

    @llvm.inline("{value}")
    def forward(value: tuple[int, ...]) -> tuple[int, ...]:
        return value

    @llvm.inline("{value}")
    def nested(value: list[tuple[int, ...]]) -> list[tuple[int, ...]]:
        return value

    @llvm.inline("{value}")
    def narrow(value: int) -> int8:
        return int8(value)

    @llvm.inline("{value}")
    def rounded(value: float) -> float32:
        return float32(value)

    class Box:
        def __init__(self, value: int):
            self.value = value

        @llvm.inline("{self}")
        def identity(self) -> Box:
            return self

    def pack(*values: int) -> tuple[int, ...]:
        return values

    def main() -> str:
        values = pack(9, 3, 4)
        rows = [values]
        assert forward(values) is values
        assert forward(value=values) is values
        assert nested(rows) is rows
        assert nested(value=rows)[0] is values
        box = Box(9)
        assert box.identity() is box
        assert box.identity().value == 9
        return str(len(forward(values))) + str(narrow(257)) + str(rounded(16777217.0))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("source", [
    '''
    def collect(a: str, /, b: str = "b", *, c: str = "c") -> str:
        return a + b + c

    def value(events: list[str], text: str) -> str:
        events.append(text)
        return text

    def main() -> str:
        events: list[str] = []
        result = collect(value(events, "1"), c=value(events, "3"), b=value(events, "2"))
        return result + ":" + "".join(events) + collect("a")
    ''',
    '''
    def collect(first: int, /, *values: int, extra: int = 10, **named: int) -> int:
        return first + sum(values) + extra + sum(named.values())

    def main() -> str:
        return str(collect(1, 2, 3, first=4, b=5)) + str(collect(1, extra=0))
    ''',
    '''
    from pyjs.native import gc_collect, gc_set_threshold

    def collect(*values: str) -> tuple[str, ...]:
        return values

    def record(**values: str) -> dict[str, str]:
        return values

    def later() -> str:
        gc_collect()
        return "last"

    def main() -> str:
        gc_set_threshold(1)
        values = collect("first" + "!", later())
        named = record(first="first" + "!", last=later())
        gc_collect()
        return "|".join(values) + "|".join(named.values()) + str(len(values))
    ''',
    '''
    class Parent:
        def __init__(self, base: int = 2, *values: int, **named: int):
            self.total = base + sum(values) + sum(named.values())

        def calculate(self, *values: int, **named: int) -> int:
            return self.total + sum(values) + sum(named.values())

    class Child(Parent):
        def calculate(self, *values: int, **named: int) -> int:
            return self.total * 2 + sum(values) + sum(named.values())

    def use(value: Parent) -> int:
        return value.calculate(3, 4, named=5)

    def main() -> str:
        return str(use(Child(2, 3, b=4))) + str(use(Parent()))
    ''',
    '''
    def consume(values: tuple[int, ...]) -> int:
        result = values[-1] if values else 0
        for value in reversed(values):
            result += value
        return result + len(values)

    def pack(*values: int) -> int:
        return consume(values)

    def main() -> str:
        return str(consume((2, 3))) + str(pack(2, 3)) + str(pack())
    ''',
    '''
    from pyjs import int8, float32

    def consume(*values: int8, **weights: float32) -> str:
        return str(sum(values, int8(0))) + str(sum(weights.values(), float32(0)))

    def main() -> str:
        return consume(int8(120), int8(20), first=float32(1.5), last=float32(2.5))
    ''',
    '''
    def values() -> tuple[int, ...]:
        return (9, 3, 4)

    def collect(*values: tuple[int, ...], **named: tuple[int, ...]) -> int:
        return len(values[0]) + len(named["a"])

    def main() -> str:
        value = values()
        return str(len(value)) + ":" + str(collect(value, a=value))
    ''',
    '''
    def consume(*values: int) -> str:
        result = str(values.count(3)) + str(values.index(3)) + str(4 in values)
        for value in reversed(values):
            result += str(value)
        try:
            values[100]
        except IndexError as error:
            result += str(error)
        try:
            values.index(100)
        except ValueError as error:
            result += str(error)
        return result

    def main() -> str:
        return consume(9, 3, 4)
    ''',
    '''
    def fail(events: list[int]) -> int:
        events.append(1)
        raise ValueError("argument")

    def later(events: list[int]) -> int:
        events.append(2)
        return 2

    def consume(*values: int, **named: int) -> int:
        raise RuntimeError("must not be called")

    def main() -> str:
        events: list[int] = []
        try:
            consume(fail(events), later(events), a=later(events))
        except ValueError:
            pass
        return str(len(events)) + str(events[0])
    ''',
], ids=["binding-order", "packs", "retained-packs", "virtual-calls", "tuple-iteration",
        "numeric-formats", "nested-packs", "tuple-search", "argument-failure"])
def test_bound_call_contracts(source, optimize):
    LLVM().assert_matches_python(source, optimize=optimize)


@pytest.mark.parametrize("signature, body, invocation", [
    ("*values: tuple[int, ...]", "return len(values[0])", "consume(value)"),
    ("**values: tuple[int, ...]", "return len(values['a'])", "consume(a=value)"),
])
def test_argument_packs_preserve_tuple_views(signature, body, invocation):
    source = f'''def consume({signature}) -> int:
    {body}

def main() -> int:
    value = (9, 3, 4)
    return {invocation}
'''
    LLVM().assert_matches_python(source)


@pytest.mark.parametrize("statement, selected", [
    ("items.append(value)", "items[-1]"),
    ("items[0] = value", "items[0]"),
    ("items.insert(0, value)", "items[0]"),
    ("named['a'] = value", "named['a']"),
    ("pass", "named.setdefault('missing', value)"),
    ("pass", "named.get('missing', value)"),
    ("named['a'] = value", "named.pop('a', value)"),
    ("pass", "named.pop('missing', value)"),
    ("other: list[tuple[int, ...]] = [value]", "other[0]"),
    ("mapping: dict[str, tuple[int, ...]] = {'a': value}", "mapping['a']"),
])
def test_collection_storage_preserves_tuple_aliases(statement, selected):
    LLVM().assert_matches_python(f'''
        def pack(*values: int) -> tuple[int, ...]:
            return values

        def main() -> int:
            value = (9, 3, 4)
            items = [pack(9, 3, 4)]
            named = {{'a': pack(9, 3, 4)}}
            {statement}
            assert {selected} is value
            return len(items[0]) + sum(items[0]) + len(named)
        ''')


@pytest.mark.parametrize("signature", ["*values: int", "**values: int", "*, value: int = 1"])
@pytest.mark.parametrize("target", ["executable", "library"])
def test_entry_wrappers_reject_unbound_parameters(signature, target):
    with pytest.raises(LLVMUnsupported, match="entry point.*cannot take"):
        transpile_llvm(f"def main({signature}) -> str:\n    return 'ok'\n", target=target)


@pytest.mark.parametrize("base_type, child_type", [
    ("tuple[int, int]", "tuple[int, ...]"),
    ("tuple[int, ...]", "tuple[int, int]"),
    ("list[tuple[int, int]]", "list[tuple[int, ...]]"),
])
@pytest.mark.parametrize("boundary", ["parameter", "return", "field", "pack", "keywords"])
def test_inherited_tuple_layouts_are_checked(base_type, child_type, boundary):
    value = "[(9, 3)]" if base_type.startswith("list") else "(9, 3)"
    if boundary in {"parameter", "pack", "keywords"}:
        star = {"pack": "*", "keywords": "**"}.get(boundary, "")
        base = f"def size(self, {star}values: {base_type}) -> int:\n        return len(values)"
        child = base.replace(base_type, child_type)
        invocation = f"return value.size({'a=' if boundary == 'keywords' else ''}{value})"
    elif boundary == "return":
        base = f"def size(self) -> {base_type}:\n        return {value}"
        child = base.replace(base_type, child_type)
        invocation = "return len(value.size())"
    else:
        base = f"def __init__(self):\n        self.values: {base_type} = {value}"
        child = base.replace(base_type, child_type)
        invocation = "return len(value.values)"
    LLVM().assert_matches_python(f'''class Parent:
    {base}

class Child(Parent):
    {child}

def use(value: Parent) -> int:
    {invocation}

def main() -> int:
    return use(Child())
''')


@pytest.mark.parametrize("signature", ["value: int = 1", "*, value: int = 1"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_defaults_belong_to_the_runtime_override(signature, optimize):
    comparison = LLVM().assert_matches_python(f'''class Parent:
    def size(self, {signature}) -> int:
        return value

class Child(Parent):
    def size(self, {signature.replace('= 1', '= 3')}) -> int:
        return value + 10

def use(value: Parent) -> int:
    return value.size()

def main() -> int:
    return use(Child())
''', optimize=optimize)
    assert comparison.native.returncode == 13
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("signature, body", [
    ("value: int", "value"),
    ("other: int = 3", "other"),
    ("value: int = 3, /", "value"),
    ("*, value: int = 3", "value"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_defaults_bind_the_selected_signature(tmp_path, signature, body, optimize):
    comparison = LLVM().assert_matches_python(f'''
            class Parent:
                def size(self, value: int = 1) -> int:
                    return value
            class Child(Parent):
                def size(self, {signature}) -> int:
                    return {body}
            def use(value: Parent) -> int:
                try:
                    return value.size()
                except TypeError:
                    return -1
            def main() -> int:
                assert use(Parent()) == 1
                return use(Child())
        ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("expression", [
    "fixed == variable", "fixed != variable", "variable == fixed",
    "(fixed,) == (variable,)", "variable in (fixed,)",
    "(fixed,).count(variable)", "(fixed,).index(variable)",
    "len({'a': [variable]}.pop('missing', [fixed])[0])",
])
@pytest.mark.parametrize("items", ["5,", "5, 6"])
def test_tuple_comparison_search_and_nested_defaults_preserve_views(expression, items):
    LLVM().assert_matches_python(f'''
        def pack(*values: int) -> tuple[int, ...]:
            return values

        def main() -> str:
            fixed = ({items})
            variable = pack({items})
            return str({expression})
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_variable_tuple_truth_reductions_and_mapping_defaults(optimize):
    LLVM().assert_matches_python('''
    def pack(*values: int) -> tuple[int, ...]:
        return values

    def main() -> str:
        empty = pack()
        full = pack(1)
        result = ""
        for values in [[empty], [full], [empty, full], [full, empty]]:
            result += str(any(values)) + str(all(values))
            result += str(any(iter(values))) + str(all(iter(values)))
        named = {"a": [full]}
        result += str(len(named.pop("a", [empty])[0]))
        result += str(len(named.pop("missing", [empty])[0]))
        return result + str(bool(empty)) + str(bool(full))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_defaults_with_matching_binding(optimize):
    LLVM().assert_matches_python('''
    class Parent:
        def size(self, value: int = 2, *, scale: int = 3) -> int:
            return value * scale

    class Child(Parent):
        def size(self, value: int = 2, *, scale: int = 3) -> int:
            return 10 + value * scale

    def use(value: Parent) -> str:
        return str(value.size()) + str(value.size(4)) + str(value.size(scale=5))

    def main() -> str:
        return use(Parent()) + use(Child())
    ''', optimize=optimize)


@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_argument_pack_allocation_failures_leave_inputs_intact(tmp_path, managed, optimize):
    from tests.native.allocation_support import run_allocation_case

    source = f'''
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def consume(*values: str, **named: str) -> str:
    return "|".join(values) + "|".join(named.values())

def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    text = "source" + "!"
    attempt = 1
    failures = 0
    while attempt < 80:
        arm(attempt)
        complete = False
        try:
            result = consume(text, text, first=text, last=text)
            arm(0)
            assert result == "source!|source!source!|source!"
            complete = True
        except MemoryError:
            arm(0)
            failures += 1
        finally:
            arm(0)
        {"gc_collect()" if managed else "pass"}
        assert text == "source!"
        assert consume(text, text, first=text, last=text) == "source!|source!source!|source!"
        if complete:
            return 0 if failures else 1
        attempt += 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)
