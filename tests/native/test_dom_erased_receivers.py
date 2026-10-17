"""An erased receiver must not discard the proof of its static DOM type."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM

ELEMENTS = '''
from typing import Iterator, cast, overload
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Left(CustomElement):
    pass
class Right(CustomElement):
    pass
class Panel(CustomElement):
    def addEventListener(self, type: str, callback: object) -> None:
        self.setAttribute('data-event', type)
'''


@pytest.mark.parametrize("result_type", ["object", "Left | Panel", "Left | None"])
@pytest.mark.parametrize("selected_type", ["Left", "Left | Right"])
def test_erased_overload_result_requires_its_runtime_projection(result_type, selected_type):
    source = ELEMENTS + f'''
@overload
def projected(value: Left, kind: int) -> {selected_type}: ...
@overload
def projected(value: Left, kind: str) -> {result_type}: ...
def projected(value: Left, kind: int | str) -> {result_type}:
    return value
def main() -> str:
    Panel()
    value = Left()
    projected(value, 0).addEventListener('change', None)
    return render_html(value)
'''
    with pytest.raises(LLVMUnsupported, match="bind the checked receiver first"):
        transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_bound_overload_result_executes_its_projection(tmp_path, optimize):
    result = LLVM().run_source(ELEMENTS + '''
@overload
def projected(value: object, kind: int) -> Left: ...
@overload
def projected(value: object, kind: str) -> object: ...
def projected(value: object, kind: int | str) -> object:
    return value
def main() -> str:
    good = projected(Left(), 0)
    good.addEventListener('change', None)
    try:
        bad = projected(Panel(), 0)
        bad.addEventListener('change', None)
    except TypeError:
        return 'checked:' + render_html(good)
    return 'missed-check'
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    # CPython's typing.overload is unchecked; native's existing checked-result
    # contract deliberately rejects the incompatible second result.
    assert result.returncode == 0
    assert result.stdout == 'checked:<pyjs-left data-self-id="ce1"></pyjs-left>'
    assert result.stderr == ""


ITERATOR = '''
class Items:
    def __init__(self, values: list[object]):
        self.values = values
        self.index = 0
    def __iter__(self) -> Iterator[Left]: return self
    def __next__(self) -> Left:
        if self.index >= len(self.values):
            raise StopIteration()
        value = cast(Left, self.values[self.index])
        self.index += 1
        return value
'''


@pytest.mark.parametrize("receiver", [
    "next(Items([panel]))", "next(iter(Items([panel])))",
    "list(Items([panel]))[0]", "[item for item in Items([panel])][0]",
])
def test_erased_iterator_receiver_follows_implicit_protocol_methods(receiver):
    with pytest.raises(LLVMUnsupported, match="bind the checked receiver first"):
        transpile_llvm(ELEMENTS + ITERATOR + f'''
def main() -> str:
    panel = Panel()
    {receiver}.addEventListener('change', None)
    return render_html(panel)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_bound_iterator_receiver_keeps_checked_protocol_evaluation(tmp_path, optimize):
    comparison = LLVM().assert_matches_python(ELEMENTS + ITERATOR + '''
def main() -> str:
    value = next(Items([Left()]))
    value.addEventListener('change', None)
    return render_html(value)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_receivers_without_any_competing_override_remain_erased(tmp_path, optimize):
    comparison = LLVM().assert_matches_python(ELEMENTS + '''
def main() -> str:
    value = Left()
    values = [value]
    next(iter(values)).addEventListener('change', None)
    list(values)[0].addEventListener('change', None)
    [item for item in values][0].addEventListener('change', None)
    return render_html(value)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


CHECKED_RECEIVERS = {
    "reflected": ('''
class Operand:
    def __init__(self, value: object): self.value = value
    def __add__(self, other: Operand) -> Left: return Left()
    def __radd__(self, other: Operand) -> Left: return Left()
class Reflected(Operand):
    def __radd__(self, other: Operand) -> Left: return cast(Left, self.value)
def operand(value: object) -> Operand: return Reflected(value)
''', "    ", "", "Operand(None) + operand(panel)"),
    "field": ('''
class Holder:
    def __init__(self, value: Left | Panel): self.value = value
def swap(holder: Holder, value: Left | Panel) -> None: holder.value = value
''', "        ", '''    holder = Holder(Left())
    if isinstance(holder.value, Left):
        swap(holder, panel)
''', "holder.value"),
    "generator": ('''
def generate(items: list[object]) -> Iterator[Left]:
    for item in items:
        yield cast(Left, item)
''', "    ", "", "next(generate([panel]))"),
}


@pytest.mark.parametrize("case", CHECKED_RECEIVERS)
def test_complex_erased_receivers_require_normal_emission_checks(case):
    declarations, indent, setup, receiver = CHECKED_RECEIVERS[case]
    with pytest.raises(LLVMUnsupported, match="bind the checked receiver first"):
        transpile_llvm(ELEMENTS + declarations + '''
def main() -> str:
    panel = Panel()
''' + setup + f"{indent}({receiver}).addEventListener('change', None)\n    return render_html(panel)\n")


@pytest.mark.parametrize("case", CHECKED_RECEIVERS)
@pytest.mark.parametrize("optimize", [0, 2])
def test_bound_receivers_retain_runtime_checks(tmp_path, case, optimize):
    declarations, indent, setup, receiver = CHECKED_RECEIVERS[case]
    source = ELEMENTS + declarations + '''
def main() -> str:
    panel = Panel()
''' + setup + f'''{indent}try:
{indent}    checked = {receiver}
{indent}    checked.addEventListener('change', None)
{indent}except TypeError:
{indent}    return 'checked'
    return 'missed-check'
'''
    # CPython casts are unchecked; LLVM deliberately checks these boundaries.
    result = LLVM().run_source(source, directory=tmp_path, optimize=optimize,
                               sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stdout == "checked"
    assert result.stderr == ""


def test_narrowed_local_receiver_uses_its_physical_declaration():
    with pytest.raises(LLVMUnsupported, match="copy narrowed local 'value' to a new local"):
        transpile_llvm(ELEMENTS + '''
def main() -> str:
    Panel()
    value: Left | Panel = Left()
    if isinstance(value, Left):
        value.addEventListener('change', None)
    return render_html(value)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_binding_a_narrowed_local_retains_the_load_check(tmp_path, optimize):
    comparison = LLVM().assert_matches_python(ELEMENTS + '''
def main() -> str:
    Panel()
    value: Left | Panel = Left()
    if isinstance(value, Left):
        checked = value
        checked.addEventListener('change', None)
    return render_html(value)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("second", ["Left", "Right"])
def test_union_overload_projection_checks_tags_without_unboxing(tmp_path, optimize, second):
    actual = "Left | Panel" if second == "Left" else "Left | Right | Panel"
    result = LLVM().run_source(ELEMENTS + f'''
@overload
def projected(value: {actual}, kind: int) -> Left | Right: ...
@overload
def projected(value: {actual}, kind: str) -> {actual}: ...
def projected(value: {actual}, kind: int | str) -> {actual}:
    return value
def main() -> str:
    left = projected(Left(), 0)
    right = projected({second}(), 0)
    left.addEventListener('change', None)
    right.addEventListener('change', None)
    try:
        bad = projected(Panel(), 0)
        bad.addEventListener('change', None)
    except TypeError:
        return render_html(left) + render_html(right)
    return 'missed-check'
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert result.stdout == ('<pyjs-left data-self-id="ce1"></pyjs-left>'
                             f'<pyjs-{second.lower()} data-self-id="ce2"></pyjs-{second.lower()}>')
    assert result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_override_free_erased_constructor_with_application_iteration(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Items:
    def __init__(self, values: list[str]): self.values = values
    def __iter__(self) -> Iterator[str]: return iter(self.values)
class Card(CustomElement):
    def __init__(self, model: Items):
        super().__init__()
        for name in model:
            self.setAttribute('data-' + name, '1')
def main() -> str:
    card = Card(Items(['a']))
    Card(Items(['b'])).addEventListener('click', None)
    return render_html(card)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("box", ["Box", "Derived"])
def test_erased_constructor_follows_property_setters_and_overrides(box):
    setter = "cast(Left, value)" if box == "Box" else "Left()"
    with pytest.raises(LLVMUnsupported, match="bind the checked receiver first"):
        transpile_llvm(ELEMENTS + f'''
class Box:
    def __init__(self, value: object):
        self._stored = Left()
        self.element = value
    @property
    def element(self) -> Left: return self._stored
    @element.setter
    def element(self, value: object) -> None: self._stored = {setter}
class Derived(Box):
    @Box.element.setter
    def element(self, value: object) -> None: self._stored = cast(Left, value)
def main() -> str:
    panel = Panel()
    {box}(panel).element.addEventListener('change', None)
    return render_html(panel)
''')
