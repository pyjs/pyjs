import uuid
from datetime import UTC, date, datetime

import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    CUSTOM_ARITHMETIC_CONTRACT,
    UNION_REFLECTED_ARITHMETIC_CONTRACT,
)


def test_uuid_host_input_reads_the_public_hex_property(tmp_path):
    result = LLVM().assert_library_matches_python('''
        from uuid import UUID
        from pyjs.native import gc_collect
        def render(value: UUID) -> str:
            gc_collect()
            return str(value) + '/' + str(value == UUID(value.hex))
    ''', uuid.UUID("12345678-9abc-def0-1234-56789abcdef0"),
        directory=tmp_path, entry_point="render")
    result.library.close()


@pytest.mark.parametrize("annotation, value, diagnostic", [
    ("datetime", datetime(2024, 1, 1, tzinfo=UTC), "naive datetime"),
    ("date", datetime(2024, 1, 1), "exact date"),
    ("date", {"year": 2024, "month": 1, "day": 1}, "exact date"),
])
def test_calendar_host_models_reject_lossy_structural_copies(tmp_path, annotation, value, diagnostic):
    library = LLVM().compile_library(f'''
        from datetime import date, datetime
        def render(value: {annotation}) -> str:
            return str(value)
    ''', tmp_path, entry_point="render")
    try:
        with pytest.raises(TypeError, match=diagnostic):
            library.render(value)
        valid = datetime(2024, 1, 1) if annotation == "datetime" else date(2024, 1, 1)
        assert library.render(valid) == str(valid)
    finally:
        library.close()


def test_path_host_input_has_an_explicit_text_boundary(tmp_path):
    from pyjs.native.llvm import LLVMUnsupported
    with pytest.raises(LLVMUnsupported, match="path inputs require text"):
        LLVM().compile_library('''
            from pathlib import PurePosixPath
            def main(value: PurePosixPath) -> str:
                return str(value)
        ''', tmp_path)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("contract", [CUSTOM_ARITHMETIC_CONTRACT, UNION_REFLECTED_ARITHMETIC_CONTRACT],
                         ids=["concrete", "union-reflected"])
def test_custom_arithmetic_protocols(tmp_path, optimize, contract):
    result = LLVM().assert_matches_python(contract.source,
                                         directory=tmp_path, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind, value", [("int", "7"), ("float", "1.5"), ("str", "'yes'")])
def test_overload_result_projects_nullable_implementation_before_direct_consumption(optimize, kind, value):
    result = LLVM().assert_matches_python(f'''
        from typing import overload
        class Box:
            @overload
            def __add__(self, value: int) -> {kind}: ...
            @overload
            def __add__(self, value: str) -> None: ...
            def __add__(self, value: int | str) -> {kind} | None:
                if isinstance(value, int):
                    return {value}
                return None
        def main() -> str:
            stored = Box() + 1
            return str(stored) + '/' + str(Box() + 1) + '/' + str(Box() + 'missing')
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_overloaded_operator_projects_its_implementation_union_result(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import overload
        from pyjs.native import gc_collect, gc_set_threshold

        class Number:
            @overload
            def __add__(self, other: int) -> int: ...
            @overload
            def __add__(self, other: str) -> str: ...
            def __add__(self, other: int | str) -> int | str:
                gc_collect()
                if isinstance(other, int):
                    if other == 0:
                        return True
                    return other + 1
                return other + "!"

        def main() -> str:
            gc_set_threshold(1)
            value = Number()
            count = value + 3
            boolean = value + 0
            copied = boolean
            text = value + "hello"
            gc_collect()
            return str(count * 2) + text.upper() + repr(copied) + str(isinstance(copied, bool))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_literal_strings_keep_string_storage_in_defaults_and_unions(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Literal

        def choose(value: int | Literal["missing"] = "missing") -> str:
            if isinstance(value, str):
                return value
            return str(value)

        def literal(value: Literal["x"]) -> str:
            return f"{value:>3}" + repr(value)

        def main() -> str:
            return choose() + choose(3) + literal("x")
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("source", [
    '''
    from uuid import UUID

    def main() -> str:
        value = UUID("{12345678-9ABC-def0-1234-56789abcdef0}")
        result = [str(value), value.hex, str(value == UUID(value.hex))]
        for text in ["short", "z" * 32]:
            try:
                UUID(text)
            except ValueError as error:
                result.append(str(error))
        return "|".join(result)
    ''',
    '''
    from datetime import date, datetime, timedelta

    def main() -> str:
        value = date(2024, 2, 29)
        stamp = datetime(2024, 2, 29, 23, 59, 59, 123456)
        duration = timedelta(days=-1, seconds=5, microseconds=3)
        return "|".join([str(value), str(stamp), str(duration),
                         str(value.weekday()), str(value.toordinal()),
                         str(duration.total_seconds()), stamp.isoformat(timespec="milliseconds")])
    ''',
    '''
    from pathlib import PurePosixPath

    def main() -> str:
        value = PurePosixPath("//root", "folder/./", "data.tar.gz")
        return "|".join([str(value), value.name, value.stem, value.suffix,
                         str(value.parts), str(value.parent),
                         str(value.with_suffix(".xz")), str(value / "next"),
                         str(value.relative_to("//root"))])
    ''',
], ids=["uuid", "calendar", "paths"])
def test_stdlib_models_compile_as_ordinary_python(tmp_path, optimize, source):
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_ord_decodes_one_scalar_and_reports_character_length(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            output: list[str] = []
            for value in ["a", "é", "€", "😀", "", "é😀", "\\0"]:
                try:
                    output.append(str(ord(value)))
                except TypeError as error:
                    output.append(str(error))
            return "|".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("constructor, fields", [
    ("date(2024, 2, 29)", "year month day"),
    ("datetime(2024, 2, 29)", "year month day hour minute second microsecond fold"),
    ("timedelta(days=1)", "days seconds microseconds"),
    ("UUID('123456789abcdef0123456789abcdef0')", "hex"),
])
def test_stdlib_value_attributes_are_read_only(constructor, fields):
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.native.llvm import transpile_llvm

    for field in fields.split():
        with pytest.raises(CompilationError, match=f"Property '{field}' is read-only"):
            transpile_llvm(f'''
                from datetime import date, datetime, timedelta
                from uuid import UUID

                def main() -> str:
                    value = {constructor}
                    value.{field} = value.{field}
                    return str(value)
            ''')
