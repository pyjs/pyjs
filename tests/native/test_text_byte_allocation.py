import pytest

from pyjs.native.llvm import transpile_llvm_module
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("expression, check", [
    ('chr(0x1f600)', 'result == "😀" and len(result) == 1'),
    ('bytes(4)', 'result.hex() == "00000000"'),
    ('bytes(items)', 'result.hex() == "00ff41"'),
    ('text.encode()', 'result.decode() == text'),
    ('encoded.decode()', 'result == text'),
    ('blob.hex()', 'result == "00ff41"'),
    ('str(blob)', 'result == "b\\\'\\\\x00\\\\xffA\\\'"'),
    ('blob[::-1]', 'result.hex() == "41ff00"'),
    ('blob.replace(b"", b"x")', 'result.hex() == "780078ff784178"'),
    ('blob.split(b"\\xff")', 'len(result) == 2 and result[1] == b"A"'),
    ('b"|".join(parts)', 'result == b"a|b"'),
    ('text.partition("é")', 'result[0] == "caf" and result[2] == ""'),
    ('text.removesuffix("é")', 'result == "caf"'),
    ('lines.splitlines(True)', 'len(result) == 2 and result[1] == "b"'),
    ('text.center(8, "😀")', 'result == "😀😀café😀😀"'),
    ('text.zfill(6)', 'result == "00café"'),
    ('tabs.expandtabs(4)', 'result == "é   x"'),
])
@pytest.mark.parametrize("forced_gc", [False, True], ids=["inferred", "forced-gc"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_text_byte_allocation_failure_sweep(tmp_path, expression, check, forced_gc, optimize):
    source = f'''
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def main() -> int:
    {"gc_set_threshold(1)" if forced_gc else "pass"}
    text = "café"
    encoded = text.encode()
    items = [0, 255, 65]
    blob = b"\\x00\\xffA"
    parts = [b"a", b"b"]
    lines = "a\\r\\nb"
    tabs = "é\\tx"
    caught = 0
    for attempt in range(1, 100):
        succeeded = False
        try:
            arm(attempt)
            result = {expression}
            arm(0)
            assert {check}
            succeeded = True
        except MemoryError:
            arm(0)
            caught += 1
        finally:
            arm(0)
        {"gc_collect()" if forced_gc else "pass"}
        assert text == "café" and blob.hex() == "00ff41"
        assert items[1] == 255 and len(parts) == 2
        result = {expression}
        assert {check}
        if succeeded:
            return 0 if caught > 0 else 1
    return 2
'''
    module = transpile_llvm_module(source)
    # Conservative inference can require GC even without explicit collection.
    # Instrument the selected allocator, not only the requested stress mode.
    run_allocation_case(module.llvm_ir, tmp_path, managed=module.managed, optimize=optimize)
