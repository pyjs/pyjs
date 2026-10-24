from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import DICTIONARY_KEYS_CONTRACT


def test_shared_dictionary_keys_contract(tmp_path):
    result = LLVM().assert_matches_python(DICTIONARY_KEYS_CONTRACT.source, directory=tmp_path)
    assert result.native.returncode == 0, DICTIONARY_KEYS_CONTRACT.failure(result.native.returncode)
