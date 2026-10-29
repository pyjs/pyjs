import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    AWAIT_ATTRIBUTE_SOURCE,
    BENCHMARK_PRIMITIVE_CONTRACTS,
    DICTIONARY_POP_CONTRACT,
    EXPLICIT_SPLIT_CONTRACT,
    LIST_TRUTH_CONTRACT,
    LOCAL_COLLECTION_CONTRACT,
    NARROWED_METHOD_CONTRACT,
    RECEIVER_DOMAIN_CONTRACTS,
    REPLACED_ATTRIBUTE_CONTRACT,
    REPLACED_RECEIVER_CONTRACTS,
)


@pytest.mark.parametrize("contract", BENCHMARK_PRIMITIVE_CONTRACTS.values(), ids=BENCHMARK_PRIMITIVE_CONTRACTS)
@pytest.mark.parametrize("optimize", [0, 2])
def test_benchmark_primitive_contract(contract, tmp_path, optimize):
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path, optimize=optimize)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)


@pytest.mark.parametrize("contract", [LIST_TRUTH_CONTRACT, EXPLICIT_SPLIT_CONTRACT, DICTIONARY_POP_CONTRACT, LOCAL_COLLECTION_CONTRACT], ids=["truth", "split", "pop", "local-collections"])
def test_client_data_contract(contract, tmp_path):
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)


def test_awaited_values_preserve_instance_attributes(tmp_path):
    result = LLVM().assert_matches_python(AWAIT_ATTRIBUTE_SOURCE + '''
def main() -> str:
    cursor = await_attributes().__await__()
    try:
        next(cursor)
    except StopIteration as error:
        return str(error.value)
    return "unexpected suspension"
''', directory=tmp_path)
    assert result.native.stdout == "readyready!ready?:-128:4"


def test_narrowed_receivers_and_arguments_keep_their_refined_type(tmp_path):
    result = LLVM().assert_matches_python(NARROWED_METHOD_CONTRACT.source, directory=tmp_path)
    assert result.native.returncode == 0


def test_replaced_attributes_do_not_keep_stale_refinements(tmp_path):
    result = LLVM().assert_matches_python(REPLACED_ATTRIBUTE_CONTRACT.source, directory=tmp_path)
    assert result.native.returncode == 0


@pytest.mark.parametrize("contract", REPLACED_RECEIVER_CONTRACTS.values(), ids=REPLACED_RECEIVER_CONTRACTS)
def test_replaced_receivers_keep_base_declarations_reachable(contract, tmp_path):
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)


@pytest.mark.parametrize("contract", [
    pytest.param(contract, id=name, marks=pytest.mark.xfail(
        strict=True, raises=AssertionError,
        reason="Existing LLVM stale-field dispatch selects the leaf instead of an inherited root method",
    ) if name.startswith("replaced_") else ())
    for name, contract in RECEIVER_DOMAIN_CONTRACTS.items()
])
def test_virtual_bindings_use_the_stored_receiver_domain(contract, tmp_path):
    result = LLVM().assert_matches_python(contract.source, directory=tmp_path)
    assert result.native.returncode == 0, contract.failure(result.native.returncode)
