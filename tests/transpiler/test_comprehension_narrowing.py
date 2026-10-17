import pytest

from pyjs.analysis.analyzer import JS_ENVIRONMENT
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


@pytest.mark.parametrize("environment", [JS_ENVIRONMENT, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "llvm", "jvm-analysis", "wasm-analysis"])
@pytest.mark.parametrize("guard_first", [True, False])
def test_filter_narrowing_is_ordered_and_preserves_portable_arguments(environment, guard_first):
    filters = ("if value is not None if accept(value)" if guard_first else
               "if accept(value) if value is not None")
    source = f'''
from pyjs import int8, js
@js
def accept(value: int8) -> bool:
    return value != 0
@js
def main() -> int:
    values: list[int8 | None] = [None, int8(127)]
    return len([value + 1 for value in values {filters}])
'''
    if not guard_first:
        with pytest.raises(CompilationError, match="expects int, got int.*None") as caught:
            with analyze_source(source, wrap=False, environment=environment):
                pass
        assert caught.value.lineno == 9
        return
    # Successful analysis must reach the strictly typed callee: merely accepting
    # a comprehension node without analyzing its later filter is insufficient.
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        accept = analysis.entry_point.container.search("accept")
        assert accept in analysis.entry_point.compilation_objects


@pytest.mark.parametrize("environment", [JS_ENVIRONMENT, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "llvm", "jvm-analysis", "wasm-analysis"])
@pytest.mark.parametrize("recheck", [False, True])
def test_replaced_comprehension_receiver_invalidates_field_proof(environment, recheck):
    source = '''
from pyjs import js
@js
class Row:
    def __init__(self, label: str | None):
        self.label = label
@js
def accept(label: str) -> bool:
    return bool(label)
@js
def main() -> int:
    rows = [Row("ready")]
    return len([row for row in rows if row.label is not None
                for row in [Row(None)] RECHECK if accept(row.label)])
'''.replace("RECHECK", "if row.label is not None" if recheck else "")
    if recheck:
        with analyze_source(source, wrap=False, environment=environment):
            pass
    else:
        with pytest.raises(CompilationError, match="expects str, got.*None"):
            with analyze_source(source, wrap=False, environment=environment):
                pass
