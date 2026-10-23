"""Host implementations belong to a compilation, including nested compiles."""

import pytest

from pyjs.analysis.analyzer import _ACTIVE_ENVIRONMENT
from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.analysis import NATIVE_LIBRARY_MAPPINGS, NativeLibraryMappings
from pyjs.native.llvm import transpile_llvm_module
from pyjs.tooling.llvm import LLVM
from tests.native.host_binding_fixtures import (
    AlternateService,
    EquivalentService,
    IncompleteService,
    Service,
)

SOURCE = '''
from tests.native.host_binding_fixtures import Service
def main() -> str:
    return Service().label(17)
'''


class EquivalentMappings(NativeLibraryMappings):
    def resolve(self, value):
        return EquivalentService if value is Service else super().resolve(value)


class AlternateMappings(NativeLibraryMappings):
    def resolve(self, value):
        return AlternateService if value is Service else super().resolve(value)


class IncompleteMappings(NativeLibraryMappings):
    def resolve(self, value):
        return IncompleteService if value is Service else super().resolve(value)


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapped_source_implementation_matches_python(tmp_path, optimize):
    result = LLVM().assert_matches_python(
        SOURCE, library_mappings=EquivalentMappings(), optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.stdout == "default:18"
    assert not result.native.stderr
    comparison = LLVM().assert_library_matches_python(
        SOURCE, directory=tmp_path, library_mappings=EquivalentMappings(), optimize=optimize,
    )
    try:
        assert comparison.native == "default:18"
    finally:
        comparison.library.close()


def test_mappings_do_not_leak_between_compilations(tmp_path):
    mapped = LLVM().compile_library(SOURCE, tmp_path, name="mapped", library_mappings=AlternateMappings())
    try:
        default = LLVM().compile_library(SOURCE, tmp_path, name="default")
        try:
            assert default.render() == "default:18"
            assert mapped.render() == "alternate:18"
            assert NATIVE_LIBRARY_MAPPINGS.resolve(Service) is Service
        finally:
            default.close()
    finally:
        mapped.close()


def test_failed_mapping_restores_the_callers_environment():
    previous = _ACTIVE_ENVIRONMENT.get()
    with pytest.raises(CompilationError, match="label.*not defined"):
        transpile_llvm_module(SOURCE, library_mappings=IncompleteMappings())
    assert _ACTIVE_ENVIRONMENT.get() is previous
    assert NATIVE_LIBRARY_MAPPINGS.resolve(Service) is Service
    result = LLVM().run_source(SOURCE)
    assert result.stdout == "default:18"
    assert result.returncode == 0


def test_nested_compilation_uses_its_own_resolver():
    nested = []

    class NestedMappings(AlternateMappings):
        def resolve(self, value):
            if value is Service and not nested:
                outer = _ACTIVE_ENVIRONMENT.get()
                # Re-enter with the default policy while outer analysis is
                # selecting an implementation. No global resolver patch can
                # correctly isolate these two compilations.
                nested.append(LLVM().run_source(SOURCE).stdout)
                assert _ACTIVE_ENVIRONMENT.get() is outer
            return super().resolve(value)

    result = LLVM().run_source(SOURCE, library_mappings=NestedMappings())
    assert nested == ["default:18"]
    assert result.stdout == "alternate:18"
    assert result.returncode == 0
