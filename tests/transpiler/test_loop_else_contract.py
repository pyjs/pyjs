from textwrap import indent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from pyjs.javascript.source import compile_source
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from pyjs.webassembly import transpile_webassembly
from tests.backend_semantics import (
    LOOP_ELSE_DECLARATION_CONTRACT,
    NESTED_LOOP_ELSE_BREAK_CONTRACT,
    _contract,
)
from tests.java.test_jvm import (
    test_jvm_runs_shared_numeric_contracts as check_jvm,
)
from tests.test_numeric import (
    test_shared_numeric_contract_runs_under_cpython as check_python,
)
from tests.test_numeric import (
    test_shared_numeric_contract_runs_under_javascript as check_javascript,
)
from tests.webassembly.test_transpiler import (
    test_webassembly_runs_shared_numeric_contracts as check_webassembly,
)


def check_contract(tmp_path, backend, contract):
    check_python(contract)
    if backend == "javascript":
        check_javascript(contract)
    elif backend == "webassembly":
        check_webassembly(tmp_path, contract)
    elif backend == "jvm":
        check_jvm(tmp_path, contract)
    else:
        result = LLVM().assert_matches_python(
            contract.source, optimize=int(backend[-1]),
            sanitizers=("address", "undefined"), directory=tmp_path,
        )
        assert not result.native.stderr


@pytest.mark.parametrize("backend", ["javascript", "webassembly", "llvm-O0", "llvm-O2"])
def test_loop_else_preserves_target_and_body_declarations(tmp_path, backend):
    # JVM's verifier already rejects body-only locals after a potentially empty
    # loop. Keep its independent backend gap out of this shared-analysis repair.
    check_contract(tmp_path, backend, LOOP_ELSE_DECLARATION_CONTRACT)


@pytest.mark.parametrize("backend", ["javascript", "jvm", "webassembly", "llvm-O0", "llvm-O2"])
def test_nested_loop_else_break_targets_enclosing_loop(tmp_path, backend):
    check_contract(tmp_path, backend, NESTED_LOOP_ELSE_BREAK_CONTRACT)


@pytest.mark.parametrize("backend", ["javascript", "llvm-O0", "llvm-O2"])
@pytest.mark.parametrize("loop", ["for", "while"])
def test_terminating_loop_else_does_not_weaken_break_exit(tmp_path, backend, loop):
    iteration = ("for value in [[3], [4]][:count]:" if loop == "for" else
                 "while count > 0:\n            count -= 1\n            value = [3]")
    contract = _contract(f'''
    from pyjs import js

    @js
    def find(count: int) -> int:
        value: list[int] | None = None
        {iteration}
            break
        else:
            return -1
        return value[0]
    ''', "terminating_else", "", (
        ("empty iteration returns through else", "find(0) != -1"),
        ("break excludes the returning else", "find(1) != 3 or find(2) != 3"),
    ))
    check_contract(tmp_path, backend, contract)


@pytest.mark.parametrize("backend", ["javascript", "llvm-O0", "llvm-O2"])
@pytest.mark.parametrize("exit", ["break", "continue"])
def test_loop_else_outer_jump_does_not_reach_inner_exit(tmp_path, backend, exit):
    contract = _contract("from pyjs import js", "outer_loop_exit", f'''
    result = 0
    for count in [1, 0, 1]:
        value: list[int] | None = None
        for value in [[3]][:count]:
            break
        else:
            {exit}
        result += value[0]
    ''', (("only inner break reaches the read", f"result != {3 if exit == 'break' else 6}"),))
    check_contract(tmp_path, backend, contract)


@pytest.mark.parametrize("backend", ["javascript", "llvm-O0", "llvm-O2"])
@pytest.mark.parametrize("loop", ["for", "while"])
@pytest.mark.parametrize("suppression", ["True", "False", "None"])
@pytest.mark.parametrize("failure", ["raise ValueError('managed')", "return fail()"])
def test_loop_else_keeps_suppressed_exception_paths(tmp_path, backend, loop, suppression, failure):
    iteration = ("for value in [[3]][:count]:" if loop == "for" else
                 "while count > 0:\n            count -= 1\n            value = [3]")
    # None-returning exit cannot suppress: retain its non-null break proof.
    read = "value[0]" if suppression == "None" else "-1 if value is None else value[0]"
    exit_type = "None" if suppression == "None" else "bool"
    contract = _contract(f'''
    from pyjs import js

    @js
    class Scope:
        def __enter__(self) -> None:
            pass
        def __exit__(self, kind: object, error: object, trace: object) -> {exit_type}:
            return {suppression}

    @js
    def fail() -> int:
        raise ValueError('managed')

    @js
    def find(count: int) -> int:
        value: list[int] | None = None
        {iteration}
            break
        else:
            with Scope():
                {failure}
        return {read}

    @js
    def check(count: int) -> int:
        try:
            return find(count)
        except ValueError:
            return -2
        except TypeError:
            return -3
    ''', "suppressed_else", "", (
        ("suppression preserves the empty-loop value", f"check(0) != {-1 if suppression == 'True' else -2}"),
        ("break skips else", "check(1) != 3"),
    ))
    check_contract(tmp_path, backend, contract)


@pytest.mark.parametrize("backend", ["javascript", "llvm", "jvm", "webassembly"])
@pytest.mark.parametrize("else_body", [
    "while stop > 0:\n    if stop == 1:\n        break\n    return -2\nelse:\n    return -1",
    "while stop > 0:\n    for ignored in [0][:0]:\n        pass\n    else:\n        break\n    return -2\nelse:\n    return -1",
    "with Scope():\n    raise ValueError('suppressed')",
], ids=["while-break", "nested-for-else-break", "suppressed-raise"])
def test_apparent_else_exit_cannot_hide_incompatible_declarations(backend, else_body):
    source = '''from pyjs import js
@js
class Scope:
    def __enter__(self) -> None: pass
    def __exit__(self, kind: object, error: object, trace: object) -> bool:
        return True
@js
def probe(count: int, stop: int) -> int:
    for item in [5, 6][:count]:
        value = 5
        break
    else:
        value = 'word'
''' + indent(else_body, '        ') + '''
    return value + 1
@js
def main() -> int:
    return probe(0, 1)
'''
    compile = {"javascript": compile_source, "llvm": transpile_llvm,
               "jvm": transpile_jvm, "webassembly": transpile_webassembly}[backend]
    # These targets reject With before reaching the declaration join. Retain
    # that explicit capability boundary, not a claim of suppression support.
    message = ("context-manager regions are not implemented" if
               backend in ("jvm", "webassembly") and else_body.startswith("with ")
               else "Operator.*not supported")
    with pytest.raises(CompilationError, match=message) as caught:
        compile(source)
    assert caught.value.diagnostic.primary.span.start_position.line > 0
