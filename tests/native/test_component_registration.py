"""Static rendering omits browser registration, not application overrides."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_button_registration_does_not_reach_browser_callback(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.web.ssr import render_html
from pyjs.web.ui.button import Button

class Inherited(Button):
    pass

async def browser_only(event) -> None:
    browser_api.fetch(event.target.value)

def main() -> str:
    button = Inherited("Search")
    button.on_click(browser_only)
    return render_html(button.element)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert ">Search</button>" in result.native.stdout
    assert result.native.stderr == ""


OVERRIDE = '''
from collections.abc import Callable
from pyjs.web.ssr import render_html
from pyjs.web.ui.button import Button

class Active(Button):
    def on_click(self, callback: Callable[[], None]) -> None:
        self.setAttribute("data-active", "yes")

def callback() -> None:
    pass
'''


@pytest.mark.parametrize("optimize", [0, 2])
def test_concrete_registration_override_runs(tmp_path, optimize):
    result = LLVM().assert_matches_python(OVERRIDE + '''
def main() -> str:
    button = Active("Search")
    button.on_click(callback)
    return render_html(button.element)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert 'data-active="yes"' in result.native.stdout
    assert result.native.stderr == ""


@pytest.mark.parametrize("body", [
    '''button: Button = Active("Search")
    button.on_click(callback)
    return render_html(button.element)''',
    '''button = Button("Search")
    register(button)
    other = Active("Later")
    return render_html(other.element)''',
])
def test_base_registration_does_not_silently_skip_overrides(body):
    with pytest.raises(LLVMUnsupported, match="erased on_click overrides require a concrete application method call"):
        transpile_llvm(OVERRIDE + '''
def register(button: Button) -> None:
    button.on_click(callback)
def main() -> str:
    ''' + body)


@pytest.mark.parametrize("call", ["Button.on_click(button, callback)", "super().on_click(callback)"])
def test_explicit_base_registration_only_erases_the_base(tmp_path, call):
    source = OVERRIDE + '''
class Child(Active):
    def register(self, callback: Callable[[], None]) -> None:
        CALL
def main() -> str:
    button = Child("Search")
    button.register(callback)
    return render_html(button.element)
'''
    # super() selects Active, whose body must still run, unlike Button.on_click.
    source = source.replace("CALL", call.replace("button", "self"))
    result = LLVM().assert_matches_python(source, directory=tmp_path,
                                          sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
    assert ('data-active="yes"' in result.native.stdout) == call.startswith("super")


@pytest.mark.parametrize("receiver", ["value", "make()"])
def test_empty_application_inline_also_checks_late_overrides(receiver):
    with pytest.raises(LLVMUnsupported, match="erased notify overrides require a concrete application method call"):
        transpile_llvm('''
from pyjs import llvm
class Quiet:
    @llvm.inline("")
    def notify(self, value: int) -> None:
        pass
class Active(Quiet):
    def notify(self, value: int) -> None:
        print(value)
def make() -> Quiet:
    return Active()
def run(value: Quiet) -> None:
    RECEIVER.notify(3)
def main() -> int:
    run(Quiet())
    Active()
    return 0
'''.replace("RECEIVER", receiver))


def test_erased_registration_omits_receiver_and_argument_side_effects(tmp_path):
    # Explicit empty-inline semantics differ from CPython: the whole call is
    # discarded, so rendering side effects must be separate statements.
    result = LLVM().run_source('''
from pyjs.web.ui.button import Button
def receiver(events: list[str]) -> Button:
    events.append("receiver")
    return Button("Unused")
def argument(events: list[str]) -> object:
    events.append("argument")
    return 3
def main() -> str:
    events: list[str] = []
    receiver(events).on_click(argument(events))
    return ",".join(events)
''', directory=tmp_path)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize("annotation", ["Left | Right", "Right | Left"])
def test_erased_union_checks_each_distinct_method_implementation(annotation):
    with pytest.raises(LLVMUnsupported, match="erased notify overrides require a concrete application method call"):
        transpile_llvm('''
from pyjs import llvm
class Left:
    @llvm.inline("")
    def notify(self) -> None:
        pass
class Right:
    @llvm.inline("")
    def notify(self) -> None:
        pass
class Active(Right):
    def notify(self) -> None:
        print("must not disappear")
def run(value: ANNOTATION) -> None:
    value.notify()
def main() -> int:
    run(Left())
    run(Active())
    return 0
'''.replace("ANNOTATION", annotation))


@pytest.mark.parametrize("name", ["super", "identity"])
def test_shadowed_super_keeps_erased_override_validation(name):
    with pytest.raises(LLVMUnsupported, match="erased on_click overrides require a concrete application method call"):
        transpile_llvm(OVERRIDE + f'''
def {name}(button: Button) -> Button:
    return button
def main() -> str:
    button = Active("Search")
    {name}(button).on_click(callback)
    return render_html(button.element)
''')


def test_super_parameter_is_not_a_lexical_base_call():
    with pytest.raises(LLVMUnsupported, match="erased on_click overrides require a concrete application method call"):
        transpile_llvm(OVERRIDE + '''
def identity(button: Button) -> Button:
    return button
class Runner:
    def register(self, super: Callable[[Button], Button], button: Button) -> None:
        super(button).on_click(callback)
def main() -> str:
    button = Active("Search")
    Runner().register(identity, button)
    return render_html(button.element)
''')


@pytest.mark.parametrize("import_line", ["", "from builtins import super"])
def test_real_super_can_erase_an_inherited_button_registration(tmp_path, import_line):
    result = LLVM().assert_matches_python(import_line + '''
from pyjs.web.ui.button import Button
from pyjs.web.ssr import render_html
class Child(Button):
    def register(self) -> None:
        super().on_click(browser_only)
async def browser_only(event) -> None:
    browser_api.fetch(event.target.value)
def main() -> str:
    button = Child("Search")
    button.register()
    return render_html(button.element)
''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("scope", ["global", "local"])
@pytest.mark.parametrize("arguments", ["", "button"])
def test_method_scope_super_shadows_are_diagnosed(scope, arguments):
    name = "super" if scope == "global" else "identity"
    parameter = "button: Button" if arguments else ""
    returned = "button" if arguments else 'Active("Other")'
    binding = "super = identity" if scope == "local" else "pass"
    with pytest.raises(CompilationError, match="erased method calls require unshadowed zero-argument super"):
        transpile_llvm(OVERRIDE + f'''
def {name}({parameter}) -> Button:
    return {returned}
class Panel(Button):
    def register(self, button: Button) -> None:
        {binding}
        super({arguments}).on_click(callback)
def main() -> str:
    button = Active("Search")
    Panel("Panel").register(button)
    return render_html(button.element)
''')


def test_explicit_super_arguments_are_not_erased_before_validation():
    with pytest.raises(CompilationError, match="erased method calls require unshadowed zero-argument super"):
        transpile_llvm(OVERRIDE + '''
class Panel(Button):
    def register(self) -> None:
        super(Panel, self).on_click(callback)
def main() -> str:
    button = Panel("Search")
    button.register()
    return render_html(button.element)
''')
