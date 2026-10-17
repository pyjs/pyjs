"""Explicit constructors own new slots, not the source's representation."""

import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    SEQUENCE_CONSTRUCTOR_REPRESENTATION_CONTRACT,
    SEQUENCE_STORAGE_COERCION_CONTRACT,
    UNION_STORAGE_COERCION_CONTRACT,
)


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_sequence_constructors_keep_representations(tmp_path, optimize):
    contract = SEQUENCE_CONSTRUCTOR_REPRESENTATION_CONTRACT
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("contract", [SEQUENCE_STORAGE_COERCION_CONTRACT, UNION_STORAGE_COERCION_CONTRACT])
def test_sequence_storage_converts_copied_scalars(tmp_path, optimize, contract):
    result = LLVM().run_source(contract.source, directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0, contract.failure(result.returncode)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_frozenset_constructor_preserves_tuple_literal_positions(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8

        def main() -> int:
            plain = frozenset[int8]((127, 1))
            nullable = frozenset[int8 | None]((127, None))
            empty = frozenset[int8](())
            assert len(plain) == 2 and 1 in plain
            assert len(nullable) == 2 and None in nullable
            assert len(empty) == 0
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
