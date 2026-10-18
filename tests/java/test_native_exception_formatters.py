"""Python exception formatting reached through Java, without Python str calls."""

import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.classfile import Bytecode, ClassFile, Field, Method
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_compiles_to_android_dex, run_jvm

NATIVE_TEXT = '''
from pyjs import jvm

@jvm.native("java/lang/String", name="valueOf")
def native_text(value: object) -> str:
    return "PyjsProgram$Failure: " + str(value)

class Failure(Exception):
    def __str__(self) -> str:
        return "custom:" + super().__str__()
'''


@pytest.mark.parametrize("entry", [
    '''
def main() -> str:
    return native_text(Failure("raw"))
''',
    '''
def report(error: Exception) -> str:
    return native_text(error)

def main() -> str:
    return report(Failure("raw"))
''',
    '''
def create() -> Failure:
    return Failure("raw")

def main() -> str:
    return native_text(create())
''',
], ids=["direct", "base-parameter", "factory"])
def test_native_arguments_retain_exception_text(tmp_path, entry):
    assert_text_matches_python(NATIVE_TEXT + entry, tmp_path)


def test_native_constructor_retains_exception_text(tmp_path):
    assert_text_matches_python(NATIVE_TEXT + '''
@jvm.native("java/lang/RuntimeException")
class Wrapper(Exception):
    def __init__(self, cause: BaseException):
        super().__init__("PyjsProgram$Failure: " + str(cause))

    def getMessage(self) -> str:
        return str(self)

def main() -> str:
    return Wrapper(Failure("raw")).getMessage()
''', tmp_path)


@pytest.mark.parametrize("factory", [False, True], ids=["direct", "factory"])
@pytest.mark.parametrize("view_type", ["Throwable", "Throwable | None"])
def test_native_view_retains_exception_text(tmp_path, factory, view_type):
    result = run_jvm(NATIVE_TEXT + f'''
from typing import cast

@jvm.native("java/lang/Throwable")
class Throwable:
    def getMessage(self) -> str: ...

def create() -> Failure:
    return Failure("raw")

def read(value: Throwable) -> str:
    return value.getMessage()

def main() -> str:
    view = cast({view_type}, {"create()" if factory else 'Failure("raw")'})
    assert view is not None
    return read(view)
''', tmp_path)
    # This is a native binding call, not a CPython Throwable API. No explicit
    # Python formatting call may accidentally retain the tested method.
    assert (result.returncode, result.stdout, result.stderr) == (0, "custom:raw", "")


@pytest.mark.parametrize("view_type", ["object", "object | None", "Throwable | None"])
def test_erased_native_arguments_keep_source_formatters(tmp_path, view_type):
    assert_text_matches_python(NATIVE_TEXT + f'''
from typing import cast

@jvm.native("java/lang/Throwable")
class Throwable:
    pass

def create() -> Failure:
    return Failure("raw")

def main() -> str:
    return native_text(cast({view_type}, create()))
''', tmp_path)


def test_object_returning_native_callback_keeps_source_formatter(tmp_path):
    assert_text_matches_python(NATIVE_TEXT + '''
from typing import cast

@jvm.native("java/util/function/Supplier", interface=True)
class Supplier:
    def get(self) -> object: ...

@jvm.native("java/util/Objects", name="requireNonNullElseGet")
def or_get(value: object | None, supplier: Supplier) -> object:
    return supplier.get() if value is None else value

def create() -> Exception:
    return Failure("raw")

class Source(Supplier):
    def get(self) -> object:
        return cast(object, create())

def main() -> str:
    return native_text(or_get(None, Source()))
''', tmp_path)


def test_native_callback_result_retains_exception_text(tmp_path):
    result = run_jvm(NATIVE_TEXT + '''
@jvm.native("java/lang/RuntimeException")
class NativeError(Exception):
    def __init__(self): ...
    def getCause(self) -> BaseException | None: ...
    def printStackTrace(self) -> None: ...

class Source(NativeError):
    def getCause(self) -> BaseException | None:
        return Failure("raw")

def main() -> int:
    Source().printStackTrace()
    return 0
''', tmp_path)
    assert result.returncode == 0
    assert result.stdout == ""
    # Java's printer invokes the Python override, then formats its result.
    assert "Caused by: PyjsProgram$Failure: custom:raw\n" in result.stderr
    assert "at PyjsProgram$Source.getCause(" in result.stderr


@pytest.mark.parametrize("value", ['Failure("raw")', 'cast(object, Failure("raw"))'])
def test_native_boundary_does_not_retain_unrelated_field_only_formatters(tmp_path, value):
    assert_text_matches_python(NATIVE_TEXT + f'''
from typing import cast

class Unused(Exception):
    def __init__(self, code: int):
        self.code = code

    def __str__(self) -> str:
        return not_defined

def main() -> str:
    unused = Unused(42)
    return native_text({value}) + str(unused.code)
''', tmp_path)


@pytest.mark.parametrize("expression, expected", [
    ('{"key": Failure("raw")}', "{key=PyjsProgram$Failure: custom:raw}"),
    ('{"outer": {"key": Failure("raw")}}', "{outer={key=PyjsProgram$Failure: custom:raw}}"),
], ids=["dictionary", "nested-dictionary"])
def test_native_container_arguments_retain_exception_text(tmp_path, expression, expected):
    result = run_jvm(NATIVE_TEXT + f'''
def main() -> str:
    return native_text({expression})
''', tmp_path)
    # Java map formatting differs from Python repr; verify the native
    # representation and its callback into each managed exception's formatter.
    assert (result.returncode, result.stdout, result.stderr) == (0, expected, "")


def test_retained_formatter_can_expose_another_native_formatting_boundary(tmp_path):
    assert_text_matches_python(NATIVE_TEXT.replace(
        'return "custom:" + super().__str__()', 'return native_inner(Inner())',
    ) + '''
@jvm.native("java/lang/String", name="valueOf")
def native_inner(value: object) -> str:
    return "PyjsProgram$Inner: " + str(value)

class Inner(Exception):
    def __str__(self) -> str:
        return "nested"

def main() -> str:
    return native_text(Failure("raw"))
''', tmp_path)


def test_native_exception_formatter_dependencies_compile_to_dex(tmp_path):
    assert_compiles_to_android_dex(NATIVE_TEXT + '''
def create() -> Failure:
    return Failure("raw")

def main() -> int:
    assert native_text(create()) == "PyjsProgram$Failure: custom:raw"
    return 42
''', tmp_path)


NATIVE_HOLDER = '''
from typing import Annotated, ClassVar
from pyjs import jvm

@jvm.native("NativeHolder")
class Holder:
    value: Annotated[object, jvm.field()]
    staticValue: ClassVar[Annotated[object, jvm.field()]] = ""
    def __init__(self) -> None:
        pass
    def read(self) -> str:
        return "PyjsProgram$Failure: " + str(self.value)

@jvm.native("NativeHolder", name="readStatic")
def read_static() -> str:
    return "PyjsProgram$Failure: " + str(Holder.staticValue)

class Child(Holder):
    pass
'''


def write_native_holder(directory):
    # Java reads the Object field and formats its contents, without an
    # analyzed Python field read or formatting call retaining the override.
    helper = ClassFile("NativeHolder", access=0x0021)
    helper.add_field(Field(0x0001, "value", "Ljava/lang/Object;"))
    helper.add_field(Field(0x0009, "staticValue", "Ljava/lang/Object;"))
    code = Bytecode()
    code.local(0x19, 0)
    constructor = helper.method_reference("java/lang/Object", "<init>", "()V")
    code.emit(0xB7, constructor.to_bytes(2, "big"))
    code.emit(0xB1)
    helper.add_method(Method(0x0001, "<init>", "()V", code.render(), 1, 1))
    for static in (False, True):
        code = Bytecode()
        if not static:
            code.local(0x19, 0)
        field = helper.field_reference(
            "NativeHolder", "staticValue" if static else "value", "Ljava/lang/Object;",
        )
        code.emit(0xB2 if static else 0xB4, field.to_bytes(2, "big"))
        method = helper.method_reference(
            "java/lang/String", "valueOf", "(Ljava/lang/Object;)Ljava/lang/String;",
        )
        code.emit(0xB8, method.to_bytes(2, "big"))
        code.emit(0xB0)
        helper.add_method(Method(
            0x0009 if static else 0x0001, "readStatic" if static else "read",
            "()Ljava/lang/String;", code.render(), 1, 0 if static else 1,
        ))
    (directory / "NativeHolder.class").write_bytes(helper.render())


@pytest.mark.parametrize("body", [
    'holder = Holder()\n    holder.value = error\n    return holder.read()',
    'holder = Child()\n    holder.value = error\n    return holder.read()',
    'Holder.staticValue = error\n    return read_static()',
    'Holder.staticValue: object = error\n    return read_static()',
], ids=["instance", "inherited", "static", "annotated-static"])
def test_native_field_stores_retain_exception_text(tmp_path, body):
    write_native_holder(tmp_path)
    assert_text_matches_python(NATIVE_TEXT + NATIVE_HOLDER + f'''
def create() -> Exception:
    return Failure("raw")

def main() -> str:
    error = create()
    {body}
''', tmp_path)


def test_object_view_native_field_store_keeps_source_formatter(tmp_path):
    write_native_holder(tmp_path)
    assert_text_matches_python(NATIVE_TEXT + NATIVE_HOLDER + '''
from typing import cast

def create() -> Failure:
    return Failure("raw")

def main() -> str:
    holder = Holder()
    holder.value = cast(object, create())
    return holder.read()
''', tmp_path)


@pytest.mark.parametrize("value", ['Failure("raw")', '"plain"'])
@pytest.mark.parametrize("field", [False, True], ids=["native-call", "native-field"])
@pytest.mark.parametrize("annotation", ["object", "object | None"])
def test_object_local_annotation_has_a_consistent_boundary(value, field, annotation):
    body = "    return native_text(error)\n"
    if field:
        body = "    holder = Holder()\n    holder.value = error\n    return holder.read()\n"
    source = NATIVE_TEXT + NATIVE_HOLDER + (
        f"\ndef main() -> str:\n    error: {annotation} = {value}\n" + body
    )
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(source, filename="object_local.py")
    # Emitter locations are relative to the named function's source.
    assert str(caught.value) == (
        "JVM object-annotated locals are not implemented at line 2 "
        "while compiling object_local.main"
    )


def test_python_owned_field_on_native_subclass_does_not_retain_formatter(tmp_path):
    write_native_holder(tmp_path)
    result = run_jvm(NATIVE_HOLDER + '''
class Unused(Exception):
    def __init__(self, code: int):
        self.code = code

    def __str__(self) -> str:
        return not_defined

class Storage(Holder):
    def __init__(self):
        super().__init__()
        self.owned = Unused(42)

def main() -> str:
    holder = Storage()
    holder.value = "safe"
    return holder.read() + str(holder.owned.code)
''', tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "safe42", "")


def test_object_view_exception_formatter_dependencies_compile_to_dex(tmp_path):
    assert_compiles_to_android_dex(NATIVE_TEXT + '''
from typing import cast

@jvm.native("java/lang/Throwable")
class Throwable:
    def getMessage(self) -> str: ...

def main() -> int:
    error = Failure("raw")
    assert native_text(cast(object, error)) == "PyjsProgram$Failure: custom:raw"
    view = cast(Throwable | None, error)
    assert view is not None
    assert view.getMessage() == "custom:raw"
    return 42
''', tmp_path)


def test_native_field_exception_formatter_dependencies_compile_to_dex(tmp_path):
    assert_compiles_to_android_dex(NATIVE_TEXT + '''
from typing import Annotated

@jvm.native("android/os/Message")
class Message:
    obj: Annotated[object, jvm.field()]
    def __init__(self) -> None: ...
    def toString(self) -> str: ...

def main() -> int:
    message = Message()
    message.obj = Failure("raw")
    assert "custom:raw" in message.toString()
    return 42
''', tmp_path)
