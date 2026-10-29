import subprocess

import pytest

from pyjs.java import transpile_jvm
from pyjs.java.classfile import Bytecode, ClassFile, ExceptionHandler, Method
from pyjs.java.stack import descriptor_slots, stack_bound
from tests.backend_semantics import RANGE_LOOP_CONTRACT
from tests.java.test_jvm import java


@pytest.mark.parametrize("descriptor, expected", [
    ("(JD[DLjava/lang/String;[[J)D", (7, 2)), ("()V", (0, 0)),
    ("[J", (0, 1)), ("J", (0, 2)), ("(IFZ)J", (3, 2)),
])
def test_descriptor_slot_widths(descriptor, expected):
    assert descriptor_slots(descriptor) == expected


def test_stack_bound_counts_wide_values_calls_fields_and_arrays():
    cls = ClassFile("Slots")
    code = Bytecode()
    code.emit(0x09)  # long
    code.emit(0x0E)  # double
    code.emit(0x01)  # array reference
    ref = cls.method_reference("Owner", "call", "(JD[J)D")
    code.emit(0xB8, ref.to_bytes(2, "big"))
    field = cls.field_reference("Owner", "value", "D")
    code.emit(0xB3, field.to_bytes(2, "big"))
    code.emit(0x01)
    code.emit(0x03)
    code.emit(0x2F)  # laload
    code.emit(0xAD)
    assert stack_bound(code.render(), cls.constants.descriptors) == 5


def test_branch_backedges_wide_locals_and_handler_entry():
    code = Bytecode()
    code.emit(0x03)
    code.local(0x36, 300)
    code.mark("loop")
    code.local(0x15, 300)
    code.branch(0x99, "done")
    code.branch(0xA7, "loop")
    code.mark("done")
    code.emit(0xB1)
    handler = len(code.code)
    code.emit(0x57)
    code.emit(0x09)
    code.emit(0x0A)
    code.emit(0x61)
    code.emit(0x58)
    code.emit(0xB1)
    assert stack_bound(code.render(), {}, (ExceptionHandler(0, handler, handler),)) == 4


@pytest.mark.parametrize("code, message", [
    (b"\x57\xb1", "underflow"),
    (b"\x03\x99\x00\x04\x03\xb1", "inconsistent"),
    (b"\xa7\x00\x01", "control-flow target"),
    (b"\x10", "truncated"), (b"\xc4", "truncated"),
    (b"\xb8", "truncated"), (b"\xca", "unsupported"),
])
def test_stack_analysis_rejects_invalid_code(code, message):
    with pytest.raises(ValueError, match=message):
        stack_bound(code, {})


def test_real_jvm_accepts_computed_capacity_above_256(tmp_path):
    # A deliberately deep valid stack proves this is analysis, not a fixed cap.
    code = b"\x03" * 300 + b"\x57" * 300 + b"\xb1"
    assert stack_bound(code, {}) == 300
    cls = ClassFile("Deep")
    cls.add_method(Method(0x0009, "main", "([Ljava/lang/String;)V", code, None, 1))
    (tmp_path / "Deep.class").write_bytes(cls.render())
    result = subprocess.run([java(), "-Xverify:all", "-cp", str(tmp_path), "Deep"], capture_output=True)
    assert result.returncode == 0, result.stderr


def test_generated_methods_compute_bounds_and_verify(tmp_path, monkeypatch):
    calculated = []
    original = ClassFile.render_method

    def record(self, method):
        if method.max_stack is None:
            calculated.append((method.name, stack_bound(method.code, self.constants.descriptors, method.exception_handlers)))
        return original(self, method)

    monkeypatch.setattr(ClassFile, "render_method", record)
    compilation = transpile_jvm('''
def helper(a: int, b: float) -> float:
    return a + b
def main() -> int:
    total = 0
    for value in range(10):
        try:
            total += int(helper(value, 1.0))
        except ValueError:
            return 1
    return 0 if total == 55 else 2
''')
    compilation.write(tmp_path)
    assert calculated and all(0 <= bound < 32 for _, bound in calculated)
    assert {name for name, _ in calculated} >= {"helper", "pyjs_main"}
    result = subprocess.run([java(), "-Xverify:all", "-cp", str(tmp_path), "PyjsProgram"], capture_output=True)
    assert result.returncode == 0, result.stderr


def test_jvm_range_loop_contract_with_computed_stack_bounds(tmp_path):
    transpile_jvm(RANGE_LOOP_CONTRACT.source).write(tmp_path)
    result = subprocess.run([java(), "-Xverify:all", "-cp", str(tmp_path), "PyjsProgram"], capture_output=True)
    assert result.returncode == 0, RANGE_LOOP_CONTRACT.failure(result.returncode)


def test_computed_stack_range_loop_compiles_to_android_dex(tmp_path):
    from tests.java.test_exceptions import assert_compiles_to_android_dex
    assert_compiles_to_android_dex(RANGE_LOOP_CONTRACT.source, tmp_path)
