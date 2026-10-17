"""Instance lookup of static methods still observes the receiver's class."""

import re

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_instance_lookup_selects_runtime_class_and_own_defaults(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
class Base:
    @staticmethod
    def label(prefix: str = 'base') -> str:
        return prefix
class Child(Base):
    @staticmethod
    def label(prefix: str = 'child') -> str:
        return prefix + '!'
class Inherited(Child):
    pass
class Grand(Inherited):
    @staticmethod
    def label(prefix: str = 'grand') -> str:
        return prefix + '?'
    def parent(self) -> str:
        return super().label()
def read(value: Base) -> str:
    return value.label() + ':' + value.label('explicit')
def main() -> str:
    return '|'.join([read(Base()), read(Child()), read(Inherited()), read(Grand()),
                     Base.label(), Child.label(), Inherited.label(), Grand.label(), Grand().parent()])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("count", [1, 20])
def test_static_instance_dispatch_groups_inherited_implementations(count):
    # One call site with many concrete receiver types must not duplicate its
    # argument evaluation and method call body for every inherited class.
    classes = '\n'.join(f'class Child{i}(Base):\n    pass' for i in range(count))
    values = ', '.join(f'Child{i}()' for i in range(count))
    emitted = transpile_llvm(f'''
class Base:
    @staticmethod
    def read() -> int:
        return 1
class Override(Base):
    @staticmethod
    def read() -> int:
        return 2
{classes}
def read(value: Base) -> int:
    return value.read()
def main() -> int:
    values: list[Base] = [Override(), {values}]
    return sum(read(value) for value in values)
''')
    # Full IR includes the runtime library; count only the selected-arm labels.
    assert len(re.findall(r'^  protocol\.class\.[0-9]+:', emitted, re.MULTILINE)) == 2


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("result", ["int", "int | None", "object"])
def test_static_instance_lookup_projects_each_result(tmp_path, optimize, result):
    comparison = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    @staticmethod
    def read() -> {result}:
        return 4
class Child(Base):
    @staticmethod
    def read() -> bool:
        return True
def render(value: Base) -> str:
    result = value.read()
    gc_collect()
    return str(result) + ':' + str(isinstance(result, bool))
def main() -> str:
    gc_set_threshold(1)
    return render(Base()) + '|' + render(Child())
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_instance_void_calls_and_mixed_method_kinds(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    @staticmethod
    def record(events: list[str], value: str = 'base') -> None:
        events.append(value)
class Child(Base):
    def __init__(self) -> None:
        self.prefix = 'child'
    def record(self, events: list[str], value: str = 'instance') -> None:
        gc_collect()
        events.append(self.prefix + value)
class StaticChild(Base):
    @staticmethod
    def record(events: list[str], value: str = 'static') -> None:
        gc_collect()
        events.append(value)
def call(value: Base, events: list[str]) -> None:
    value.record(events)
    value.record(events, 'explicit')
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    call(Base(), events)
    call(Child(), events)
    call(StaticChild(), events)
    return str(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_static_instance_incompatible_reached_signature_is_diagnosed():
    with pytest.raises(LLVMUnsupported, match="missing.*extra"):
        transpile_llvm('''
class Base:
    @staticmethod
    def read() -> int:
        return 1
class Child(Base):
    @staticmethod
    def read(extra: int) -> int:
        return extra
def call(value: Base) -> int:
    return value.read()
def main() -> int:
    return call(Base()) + call(Child())
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_instance_receiver_and_expanded_arguments_run_once_in_order(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    @staticmethod
    def call(left: str, right: str, *, suffix: str = 'base') -> str:
        return left + right + suffix
class Child(Base):
    @staticmethod
    def call(left: str, right: str, *, suffix: str = 'child') -> str:
        gc_collect()
        return right + left + suffix
def receiver(events: list[str], child: bool) -> Base:
    events.append('receiver')
    if child:
        return Child()
    return Base()
def args(events: list[str]) -> tuple[str, str]:
    events.append('args')
    gc_collect()
    return ('left', 'right')
def kwargs(events: list[str]) -> dict[str, str]:
    events.append('kwargs')
    gc_collect()
    return {'suffix': 'explicit'}
def read(events: list[str], child: bool) -> str:
    return receiver(events, child).call(*args(events), **kwargs(events))
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    result = read(events, False) + '|' + read(events, True)
    return result + str(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_instance_reference_results_and_exceptions(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    @staticmethod
    def read(value: list[str], fail: bool) -> object:
        if fail:
            raise ValueError('base')
        return None
class Child(Base):
    @staticmethod
    def read(value: list[str], fail: bool) -> list[str]:
        gc_collect()
        if fail:
            raise ValueError('child')
        return value
def render(receiver: Base, values: list[str], fail: bool) -> str:
    try:
        result = receiver.read(values, fail)
        gc_collect()
        return str(result) + ':' + str(result is values)
    except ValueError as error:
        return str(error)
def main() -> str:
    gc_set_threshold(1)
    values = ['live']
    return '|'.join([render(Base(), values, False), render(Child(), values, False),
                     render(Base(), values, True), render(Child(), values, True)])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_stored_super_aliases_keep_lexical_methods_properties_and_results(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    @staticmethod
    def label(prefix: str = 'base') -> str:
        return prefix
    @staticmethod
    def number() -> int:
        return 7
    def method(self) -> str:
        return 'base-method'
    @property
    def text(self) -> str:
        return 'base-property'
class Child(Base):
    @staticmethod
    def label(prefix: str = 'child') -> str:
        return prefix
    def method(self) -> str:
        return 'child-method'
    @property
    def text(self) -> str:
        return 'child-property'
class Grand(Child):
    @staticmethod
    def label(prefix: str = 'grand') -> str:
        return prefix
    @staticmethod
    def number() -> bool:
        return True
    def method(self) -> str:
        return 'grand-method'
    @property
    def text(self) -> str:
        return 'grand-property'
    def read(self, flag: bool) -> str:
        proxy = super()
        alias = proxy
        if flag:
            other = alias
        else:
            other = super()
        for index in range(3):
            alias = other
        gc_collect()
        selected = super() if flag else alias
        annotated: Child = super()
        split: Base
        split = super()
        result = alias.number()
        callback = alias.label
        bound = alias.method
        return '|'.join([proxy.label(), other.label('explicit'), alias.label(),
                         alias.method(), alias.text, str(result), str(isinstance(result, bool)),
                         callback('callback'), bound(), super().label(), self.label(), selected.label(),
                         (alias if flag else super()).label(), annotated.label(), split.label()])
    def generate(self):
        proxy = super()
        yield proxy.label()
        gc_collect()
        yield proxy.method()
def main() -> str:
    gc_set_threshold(1)
    return Grand().read(True) + ':' + Grand().read(False) + str(list(Grand().generate()))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("body, diagnostic", [
    ("proxy = super()\n        proxy = self\n        return proxy.label()", "cannot mix super"),
    ("proxy = super()\n        if flag:\n            proxy = self\n        return proxy.label()", "cannot mix super"),
    ("proxy = super()\n        callback = lambda: proxy.label()\n        return callback()", "cannot escape into closures"),
    ("proxy = super()\n        return forward(proxy)", "not escape"),
    ("return forward(super())", "not escape"),
    ("proxy = super() if flag else self\n        return proxy.label()", "cannot mix super"),
    ("return (super() if flag else self).label()", "cannot mix super"),
])
def test_super_proxy_ambiguous_storage_and_escape_have_diagnostics(body, diagnostic):
    with pytest.raises(LLVMUnsupported, match=diagnostic):
        transpile_llvm(f'''
class Base:
    @staticmethod
    def label() -> str:
        return 'base'
class Child(Base):
    @staticmethod
    def label() -> str:
        return 'child'
    def read(self, flag: bool) -> str:
        {body}
def forward(value: Base) -> str:
    return value.label()
def main() -> str:
    return Child().read(True)
''')


def super_alias_source(body):
    return f'''
class Base:
    @staticmethod
    def label() -> str:
        return 'base'
    def method(self) -> str:
        return 'base-method'
    @property
    def text(self) -> str:
        return 'base-property'
class Child(Base):
    @staticmethod
    def label() -> str:
        return 'child'
    def method(self) -> str:
        return 'child-method'
    @property
    def text(self) -> str:
        return 'child-property'
class Grand(Child):
    @staticmethod
    def label() -> str:
        return 'grand'
    def read(self, flag: bool) -> str:
        {body}
def main() -> str:
    return Grand().read(False)
'''


@pytest.mark.parametrize("placement", ["before", "after", "conditional"])
@pytest.mark.parametrize("unpack", [False, True])
def test_super_proxy_rejects_loop_target_rebinding_in_either_order(placement, unpack):
    declaration = ("items: list[tuple[Child, int]] = [(self, 1)]" if unpack
                   else "items: list[Child] = [self]")
    target = "proxy, index" if unpack else "proxy"
    before = "proxy = super()" if placement == "before" else "pass"
    after = {"before": "pass", "after": "proxy = super()",
             "conditional": "if flag:\n            proxy = super()"}[placement]
    source = super_alias_source(f'''{declaration}
        {before}
        result = ''
        for {target} in items:
            result += proxy.label() + proxy.method() + proxy.text
        {after}
        return result''')
    with pytest.raises(LLVMUnsupported, match="super.*other local bindings"):
        transpile_llvm(source)


@pytest.mark.parametrize("use", ["proxy.label()", "proxy.method()", "proxy.text",
                                 "(proxy if flag else super()).label()"])
def test_super_proxy_rejects_annotation_that_changes_lexical_lookup(use):
    source = super_alias_source(f"proxy: Base = super()\n        return {use}")
    with pytest.raises(LLVMUnsupported, match="retain their lexical parent type"):
        transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_super_proxy_retains_specialized_lexical_type(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
class Base[T]:
    @staticmethod
    def label() -> str:
        return 'base'
class Child[T](Base[T]):
    @staticmethod
    def label() -> str:
        return 'child'
    def read(self) -> str:
        proxy = super()
        alias = proxy
        return alias.label() + self.label()
def main() -> str:
    return Child[int]().read() + Child[str]().read()
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
