import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.javascript.source import compile_source

from .helpers import assert_semantics


@pytest.mark.parametrize("argument", ["2", "other=2"])
@pytest.mark.parametrize("default", ["", " = 5"])
def test_virtual_override_optional_operand(argument, default):
    assert_semantics(f'''
        from pyjs import js
        @js
        class Base:
            def bump(self, other: int{default}) -> int:
                return other
        @js
        class Child(Base):
            def bump(self, other: int = 7) -> int:
                return other * 10
        @js
        def update(value: Base):
            print(value.bump({argument}))
        def main():
            update(Base())
            update(Child())
        main()
    ''')


def test_virtual_override_multilevel_renamed_positional_operands():
    assert_semantics('''
        from pyjs import js
        @js
        class Base:
            def total(self, first: int, second: int) -> int:
                return first + second
        @js
        class Child(Base):
            def total(self, first: int, amount: int = 7) -> int:
                return first + amount * 10
        @js
        class Grand(Child):
            def total(self, left: int = 5, right: int = 7, /) -> int:
                return left + right * 100
        @js
        def update(value: Base):
            print(value.total(2, 3))
        def main():
            update(Base())
            update(Child())
            update(Grand())
        main()
    ''')


def test_virtual_override_omission_uses_runtime_default():
    assert_semantics('''
        from pyjs import js
        @js
        class Base:
            def total(self, first: int, second: int = 2) -> int:
                return first + second
        @js
        class Child(Base):
            def total(self, first: int = 3, second: int = 7) -> int:
                return first + second * 10
        @js
        def update(value: Base):
            print(value.total(1))
        def main():
            update(Base())
            update(Child())
        main()
    ''')


def test_virtual_override_bound_method_with_changed_abi_diagnoses():
    source = '''
        from pyjs import js
        @js
        class Base:
            def total(self, value: int) -> int:
                return value
        @js
        class Child(Base):
            def total(self, value: int = 7) -> int:
                return value * 10
        @js
        def update(value: Base):
            callback = value.total
            print(callback(2))
        def main():
            update(Child())
    '''
    with pytest.raises(CompilationError, match="bound method.*calling conventions"):
        with compile_source(source):
            pass


@pytest.mark.parametrize("asynchronous", [False, True])
def test_virtual_override_evaluates_receiver_and_keywords_once_in_source_order(asynchronous):
    async_def, awaited = ("async def ", "await ") if asynchronous else ("def ", "")
    assert_semantics(f'''
        from pyjs import js
        import asyncio
        @js
        class Base:
            def total(self, first: int, second: int) -> int:
                return first + second
        @js
        class Child(Base):
            def total(self, first: int = 3, second: int = 7) -> int:
                print("method")
                return first + second * 10
        @js
        {async_def}receiver(value: Base) -> Base:
            print("receiver")
            return value
        @js
        {async_def}argument(value: int) -> int:
            print(value)
            return value
        @js
        {async_def}update(value: Base):
            print(({awaited}receiver(value)).total(
                second={awaited}argument(2), first={awaited}argument(1)))
        {async_def}main():
            {awaited}update(Child())
        {"asyncio.run(main())" if asynchronous else "main()"}
    ''')


def test_virtual_override_same_arity_renamed_options():
    assert_semantics('''
        from pyjs import js
        @js
        class Base:
            def total(self, left: int = 1) -> int:
                return left
        @js
        class Child(Base):
            def total(self, right: int = 2) -> int:
                return right * 10
        @js
        def update(value: Base):
            print(value.total(3), value.total())
        def main():
            update(Base())
            update(Child())
        main()
    ''')


@pytest.mark.parametrize("call", ["value.total(3)", "value.total(3, 4)"])
def test_virtual_override_ambiguous_same_arity_diagnoses(call):
    source = f'''
        from pyjs import js
        @js
        class Base:
            def total(self, left: int = 1, right: int = 2) -> int:
                return left + right
        @js
        class Child(Base):
            def total(self, right: int = 3, left: int = 4) -> int:
                return left * 10 + right
        @js
        def update(value: Base):
            print({call})
        def main():
            update(Child())
    '''
    with pytest.raises(CompilationError, match="ambiguous argument layouts"):
        with compile_source(source):
            pass


def test_virtual_override_super_call_uses_declared_method():
    assert_semantics('''
        from pyjs import js
        @js
        class Base:
            def total(self, value: int) -> int:
                return value
        @js
        class Child(Base):
            def total(self, value: int = 7) -> int:
                return super().total(value) * 10
        @js
        def update(value: Base):
            print(value.total(2))
        def main():
            update(Child())
        main()
    ''')


@pytest.mark.parametrize("signature", ["value: Base | Other", "value: Other | Base"])
def test_virtual_override_union_receivers(signature):
    assert_semantics(f'''
        from pyjs import js
        @js
        class Base:
            def total(self, value: int) -> int:
                return value
        @js
        class Child(Base):
            def total(self, value: int = 7) -> int:
                return value * 10
        @js
        class Other:
            def total(self, value: int) -> int:
                return value * 100
        @js
        def update({signature}):
            print(value.total(2))
        def main():
            update(Base())
            update(Child())
            update(Other())
        main()
    ''')


def test_virtual_override_specialized_generic_receiver():
    assert_semantics('''
        from pyjs import js
        @js
        class Base[T]:
            def total(self, value: T) -> T:
                return value
        @js
        class Child(Base[int]):
            def total(self, amount: int = 7) -> int:
                return amount * 10
        @js
        def update(value: Base[int]):
            print(value.total(2))
        def main():
            update(Base[int]())
            update(Child())
        main()
    ''')


@pytest.mark.parametrize("keywords", ["sample=2", ""])
@pytest.mark.parametrize("structural", [False, True])
def test_virtual_override_additional_keyword_only_defaults_preserve_call_layout(keywords, structural):
    assert_semantics(f'''
        from pyjs import js
        @js
        class Observer:
            {"__pyjs_structural__ = True" if structural else "pass"}
            def updated(self, value: int, *, sample: int = 1) -> int:
                return value + sample
        @js
        class Recorder{'' if structural else '(Observer)'}:
            def updated(self, value: int, *, sample: int = 1,
                        capture: bool = True, extra: int = 3) -> int:
                return value + sample + (extra if capture else 0)
        @js
        def update(observer: Observer):
            print(observer.updated(4, {keywords}))
        def main():
            update(Observer())
            update(Recorder())
        main()
    ''')


def test_virtual_override_varargs_options_slot_change_still_diagnoses():
    source = '''
        from pyjs import js
        @js
        class Base:
            def total(self, *values: int) -> int:
                return sum(values)
        @js
        class Child(Base):
            def total(self, *values: int, offset: int = 3) -> int:
                return sum(values) + offset
        @js
        def update(value: Base):
            print(value.total(2, 3))
        def main():
            update(Child())
    '''
    with pytest.raises(CompilationError, match="require fixed ordinary parameters"):
        with compile_source(source):
            pass
