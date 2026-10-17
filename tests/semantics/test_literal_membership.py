import pytest

from pyjs.analysis.source import analyze_source
from pyjs.testing.helpers import at

from .helpers import assert_semantics


@pytest.mark.parametrize("expression, analyzed, javascript", [
    (
        'needle in {"internal", "postmaster"}',
        "{'internal', 'postmaster'}.[set__str]__contains__!(needle)",
        "(needle === 'internal' || needle === 'postmaster')",
    ),
    (
        'needle not in {"a", "b"}',
        "not {'a', 'b'}.[set__str]__contains__!(needle)",
        "!((needle === 'a' || needle === 'b'))",
    ),
    (
        '{"a"}.__contains__(needle)',
        "{'a'}.[set__str]__contains__!(needle)",
        "(needle === 'a')",
    ),
    (
        '{"a", "b"}.__contains__(needle.lower())',
        "{'a', 'b'}.[set__str]__contains__!(needle.[str]lower!())",
        "(($item) => $item === 'a' || $item === 'b')(needle.toLowerCase())",
    ),
    (
        'needle in {"a", "b", "c", "d"}',
        "{'a', 'b', 'c', 'd'}.[set__str]__contains__!(needle)",
        "(needle === 'a' || needle === 'b' || needle === 'c' || needle === 'd')",
    ),
    (
        'needle in {"a", "b", "c", "d", "e"}',
        "{'a', 'b', 'c', 'd', 'e'}.[set__str]__contains__!(needle)",
        "(($compare_left0, $compare_right1) => $compare_right1.has($compare_left0))(needle, new Set(['a', 'b', 'c', 'd', 'e']))",
    ),
    (
        'needle in {"a", other}',
        "{'a', other}.[set__str]__contains__!(needle)",
        "(($compare_left0, $compare_right1) => $compare_right1.has($compare_left0))(needle, new Set(['a', other]))",
    ),
    (
        '"a" in {"a", "b"}',
        "{'a', 'b'}.[set__str]__contains__!('a')",
        "('a' === 'a' || 'a' === 'b')",
    ),
    (
        '"a" in {"a", other}',
        "{'a', other}.[set__str]__contains__!('a')",
        "new Set(['a', other]).has('a')",
    ),
])
def test_small_literal_string_membership_emission(expression, analyzed, javascript):
    at(
        f"def main(needle: str, other: str) -> bool:\n    return {expression}",
        f"def main(needle: str, other: str) -> bool:\n    return {analyzed}",
        "export function main(needle, other) {\n"
        f"    return {javascript};\n"
        "}",
    )


def test_numeric_sets_keep_normal_membership():
    at(
        "def main(needle: int) -> bool:\n    return needle in {1, 2}",
        "def main(needle: int) -> bool:\n"
        "    return {1, 2}.[set__int]__contains__!(needle)",
        "export function main(needle) {\n"
        "    return (($compare_left0, $compare_right1) => $compare_right1.has($compare_left0))(needle, new Set([1, 2]));\n"
        "}",
    )


def test_literal_membership_matches_python_values_and_effect_order():
    assert_semantics('''
        from pyjs import js

        @js
        def value(events: list[str], text: str) -> str:
            events.append(text)
            return text

        def main():
            events: list[str] = []
            for needle in ["", "internal", "postmaster", "missing", "漢字 😀", "a'b"]:
                print(value(events, needle) in {"internal", "postmaster"})
                print(value(events, needle) not in {"internal", "postmaster"})
                print({"", "漢字 😀", "a'b", "a'b"}.__contains__(value(events, needle)))
            print("|".join(events))
            events.clear()
            print(value(events, "needle") in {value(events, "first"), value(events, "last")})
            print("|".join(events))
            values = {"internal", "postmaster"}
            values.add("later")
            print("later" in values)
            print("internal" in values)

        main()
    ''')


def test_custom_contains_is_not_replaced():
    assert_semantics('''
        from pyjs import js

        @js
        class Bag:
            def __contains__(self, item: str) -> bool:
                print(item)
                return False

        def main():
            print("internal" in Bag())

        main()
    ''')


def test_membership_awaits_both_operands_in_source_order():
    assert_semantics('''
        import asyncio
        from pyjs import js

        @js
        async def text(events: list[str], value: str) -> str:
            events.append(value)
            return value

        @js
        async def main() -> None:
            events: list[str] = []
            print(await text(events, "key") in await text(events, "some key"))
            print("|".join(events))

        asyncio.run(main())
    ''')


@pytest.mark.parametrize("kind, literal", [
    ("list[str]", '["key"]'), ("tuple[str]", '("key",)'),
    ("set[str]", '{"key"}'), ("str", '"key"'),
])
@pytest.mark.parametrize("expression", [
    "needle(events, fail) in container(events)",
    "needle(events, fail) not in container(events)",
    "container(events).__contains__(needle(events, fail))",
])
def test_membership_operand_effects_and_failure_order(kind, literal, expression):
    # List/tuple membership forwards to an ordinary helper; set/string uses
    # inline source. Explicit methods retain receiver-first call semantics.
    assert_semantics(f'''
        from pyjs import js
        @js
        def needle(events: list[str], fail: bool) -> str:
            events.append("needle")
            if fail:
                raise ValueError("stop")
            return "key"
        @js
        def container(events: list[str]) -> {kind}:
            events.append("container")
            return {literal}
        def main() -> None:
            for fail in [False, True]:
                events: list[str] = []
                try:
                    print({expression})
                except ValueError:
                    print("failed")
                print("|".join(events))
        main()
    ''')


@pytest.mark.parametrize("kind, literal, suffix", [
    ("list[str]", '["key"]', ""), ("tuple[str]", '("key",)', ""),
    ("dict[str, str]", '{"key": "key"}', ".keys()"),
])
def test_forwarded_membership_awaits_operands_outside_capture(kind, literal, suffix):
    assert_semantics(f'''
        import asyncio
        from pyjs import js
        @js
        async def needle(events: list[str]) -> str:
            events.append("needle")
            return "key"
        @js
        async def container(events: list[str]) -> {kind}:
            events.append("container")
            return {literal}
        @js
        async def main() -> None:
            events: list[str] = []
            print(await needle(events) in (await container(events)){suffix})
            print("|".join(events))
        asyncio.run(main())
    ''')


def test_forwarded_membership_emission():
    at(
        "def main(needle: str, values: list[str]) -> bool:\n    return needle.lower() in values",
        "def main(needle: str, values: list__str) -> bool:\n"
        "    return $contains_equal_sequence_item(values, needle.[str]lower!())",
        "import { contains_equal_sequence_item as $contains_equal_sequence_item } from './pyjs.python.js';\n\n"
        "export function main(needle, values) {\n"
        "    return (($compare_left0, $compare_right1) => $contains_equal_sequence_item($compare_right1, $compare_left0))(needle.toLowerCase(), values);\n"
        "}",
    )


@pytest.mark.parametrize("expression, reverse", [
    ("needle in values", True), ("values.__contains__(needle)", False),
])
def test_forwarded_membership_keeps_source_order_metadata(expression, reverse):
    with analyze_source(
        f"def main(needle: str, values: list[str]) -> bool:\n    return {expression}",
        wrap=False,
    ) as analysis:
        call = analysis.entry_point.body[0].value
        assert call.forwarded_func.attr == "__contains__"
        assert call.reverse is reverse
        assert [argument.id for argument in call.args] == ["values", "needle"]


@pytest.mark.parametrize("needle_type, item_type", [("int64", "int"), ("int", "int64")])
def test_coerced_membership_keeps_reverse_metadata(needle_type, item_type):
    with analyze_source(
        "from pyjs import int64\n"
        f"def main(needle: {needle_type}, values: list[{item_type}]) -> bool:\n"
        "    return abs(needle) in values",
        wrap=False,
    ) as analysis:
        call = analysis.entry_point.body[0].value
        assert call.forwarded_func.attr == "__contains__"
        assert call.reverse is True


@pytest.mark.parametrize("needle_type, item_type", [("int64", "int"), ("int", "int64")])
@pytest.mark.parametrize("expression", [
    "needle(mode) in [item(mode)]", "needle(mode) in (item(mode),)",
    "needle(mode) in {item(mode)}", "needle(mode) in {item(mode): 1}",
    "needle(mode) not in [item(mode)]", "[item(mode)].__contains__(needle(mode))",
])
def test_coerced_membership_keeps_effects_and_exception_order(needle_type, item_type, expression):
    assert_semantics(f'''
        from pyjs import int64, js
        @js
        def needle(mode: int) -> {needle_type}:
            print("needle")
            if mode == 1:
                raise ValueError("needle failed")
            return {needle_type}(7)
        @js
        def item(mode: int) -> {item_type}:
            print("container item")
            if mode == 2:
                raise ValueError("container failed")
            return {item_type}(7)
        def main() -> None:
            for mode in (0, 1, 2):
                try:
                    print({expression})
                except ValueError:
                    print("failed")
        main()
    ''')


@pytest.mark.parametrize("expression", [
    "needle(events, fail) in mapping(events).keys()",
    "needle(events, fail) not in mapping(events).values()",
    '(needle(events, fail), "key") in mapping(events).items()',
    "len(needle(events, fail)) in range(stop(events))",
])
def test_generic_iterable_membership_preserves_failure_and_effect_order(expression):
    assert_semantics(f'''
        from pyjs import js
        @js
        def needle(events: list[str], fail: bool) -> str:
            events.append("needle")
            if fail:
                raise ValueError("stop")
            return "key"
        @js
        def mapping(events: list[str]) -> dict[str, str]:
            events.append("container")
            return {{"key": "key"}}
        @js
        def stop(events: list[str]) -> int:
            events.append("container")
            return 5
        def main() -> None:
            for fail in [False, True]:
                events: list[str] = []
                try:
                    print({expression})
                except ValueError:
                    print("failed")
                print("|".join(events))
        main()
    ''')


@pytest.mark.parametrize("expression", [
    "needle(fail) in container()",
    "container().__contains__(needle(fail))",
    'container().__contains__("key")',
])
def test_static_forwarded_membership_retains_receiver_effects_and_reachability(expression):
    assert_semantics(f'''
        from pyjs import js
        @js
        def contains(item: str) -> bool:
            print("compare")
            return item == "key"
        @js
        class Bag:
            @staticmethod
            @js.inline(call=contains)
            def __contains__(item: str) -> bool:
                return contains(item)
        @js
        def needle(fail: bool) -> str:
            print("needle")
            if fail:
                raise ValueError("stop")
            return "key"
        @js
        def container() -> Bag:
            print("container")
            return Bag()
        def main() -> None:
            for fail in [False, True]:
                try:
                    print({expression})
                except ValueError:
                    print("failed")
            print("key" in container())
        main()
    ''')


@pytest.mark.parametrize("expression", [
    "make(fail).run(argument())", "make(fail).run(value=argument())",
    "make(fail).run()", "Factory.run(argument())",
])
def test_static_forwarding_retains_receiver_failures_defaults_and_keywords(expression):
    assert_semantics(f'''
        from pyjs import js
        @js
        def helper(value: str = "default") -> str:
            print("helper")
            return value
        @js
        class Factory:
            @staticmethod
            @js.inline(call=helper)
            def run(value: str = "default") -> str:
                return helper(value)
        @js
        def make(fail: bool) -> Factory:
            print("receiver")
            if fail:
                raise ValueError("receiver failed")
            return Factory()
        @js
        def argument() -> str:
            print("argument")
            return "value"
        def main() -> None:
            for fail in [False, True]:
                try:
                    print({expression})
                except ValueError:
                    print("failed")
        main()
    ''')


def test_static_forwarding_awaits_in_the_enclosing_function():
    assert_semantics('''
        import asyncio
        from pyjs import js
        @js
        def helper(value: str) -> str:
            print("helper")
            return value
        @js
        class Factory:
            @staticmethod
            @js.inline(call=helper)
            def run(value: str) -> str:
                return helper(value)
        @js
        async def make() -> Factory:
            print("receiver")
            return Factory()
        @js
        async def argument() -> str:
            print("argument")
            return "value"
        @js
        async def main() -> None:
            print((await make()).run(await argument()))
        asyncio.run(main())
    ''')


@pytest.mark.parametrize("body, expression", [
    ('def value(self) -> str:\n    return super().run("instance")', 'Child().value()'),
    ('@classmethod\ndef value(cls) -> str:\n    return super().run("class")', 'Child.value()'),
    ('def __init__(self) -> None:\n    value = super().run("init")\n    super().__init__()\n    self.value = value', 'Child().value'),
    ('def value(self) -> str:\n    return super().__contains__("explicit")', 'Child().value()'),
])
def test_static_forwarding_through_super_is_lexical(body, expression):
    from textwrap import indent

    assert_semantics('''
from pyjs import js
@js
def helper(value: str) -> str:
    print("helper", value)
    return value
@js
class Base:
    def __init__(self) -> None:
        print("base init")
    @staticmethod
    @js.inline(call=helper)
    def run(value: str) -> str:
        return helper(value)
    @staticmethod
    @js.inline(call=helper)
    def __contains__(value: str) -> str:
        return helper(value)
@js
class Child(Base):
''' + indent(body, "    ") + f'''
def main() -> None:
    print({expression})
main()
''')


@pytest.mark.parametrize("name", ["super", "make"])
@pytest.mark.parametrize("invocation", ["direct", "function", "method"])
def test_static_forwarding_preserves_shadowed_super(name, invocation):
    call = f"{name}(fail).run(argument())"
    if invocation == "function":
        call = f"invoke({name}, fail)"
    elif invocation == "method":
        call = f"Runner().invoke({name}, fail)"
    assert_semantics(f'''
        from collections.abc import Callable
        from pyjs import js
        @js
        def helper(value: str) -> str:
            print("helper")
            return value
        @js
        class Base:
            @staticmethod
            @js.inline(call=helper)
            def run(value: str) -> str:
                return helper(value)
        @js
        def {name}(fail: bool) -> Base:
            print("receiver")
            if fail:
                raise ValueError("receiver failed")
            return Base()
        @js
        def argument() -> str:
            print("argument")
            return "value"
        @js
        def invoke(super: Callable[[bool], Base], fail: bool) -> str:
            return super(fail).run(argument())
        @js
        class Runner:
            def invoke(self, super: Callable[[bool], Base], fail: bool) -> str:
                return super(fail).run(argument())
        def main() -> None:
            for fail in (False, True):
                try:
                    print({call})
                except ValueError:
                    print("failed")
        main()
    ''')
