import sys

import pytest

from pyjs.analysis.diagnostics import CompilationError, format_compilation_error
from pyjs.javascript.source import compile_source
from pyjs.shader import f32
from pyjs.shader.transpiler import WGSLUnsupported, transpile_wgsl


def emit(body: str) -> str:
    return transpile_wgsl(
        "from pyjs import wgsl; from pyjs.shader import Array, f32, i32\n" + body
    )


@pytest.fixture
def package(tmp_path, monkeypatch):
    name = f"shaders_{tmp_path.name.lower().replace('-', '_')}"
    root = tmp_path / name
    root.mkdir()
    (root / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))

    def write(modules: dict[str, str]) -> str:
        for module, source in modules.items():
            (root / f"{module}.py").write_text(
                "from pyjs.shader import Array, f32, i32\n" + source
            )
        return name

    write.name = name
    yield write
    for module in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        del sys.modules[module]


def test_wgsl_decorators_use_one_metadata_record():
    from pyjs import wgsl

    @wgsl
    def total(items: list[f32]) -> f32:
        return items[0]

    @wgsl
    class Hit:
        distance: f32

    @wgsl.native
    class vec2f:
        x: f32

    @wgsl.inline("({a} % {b})")
    def fmod(a: f32, b: f32) -> f32:
        return a

    for obj in (total, Hit, vec2f, fmod):
        assert {name for name in vars(obj) if name.startswith("__wgsl")} == {"__wgsl__"}
    assert total.__wgsl__.kind == "emit" and Hit.__wgsl__.kind == "emit"
    assert vec2f.__wgsl__.kind == "native"
    assert fmod.__wgsl__.kind == "inline"
    assert fmod.__wgsl__.template == "({a} % {b})"


def test_documented_struct_and_array_example_compiles():
    source = """
    from math import sqrt

    from pyjs import wgsl
    from pyjs.shader import Array, dot, f32, i32, vec3f

    @wgsl
    class Hit:
        distance: f32
        index: i32

        def __init__(self, distance: f32, index: i32) -> None:
            self.distance = distance
            self.index = index

    @wgsl
    def nearest(p: vec3f, centres: Array[vec3f, 4]) -> Hit:
        best = Hit(1e9, -1)
        for i in range(4):
            d = centres[i] - p
            distance = sqrt(dot(d, d))
            if distance < best.distance:
                best = Hit(distance, i)
        return best
    """
    assert (
        transpile_wgsl(source)
        == """\
struct Hit {
  distance: f32,
  index: i32,
}

fn nearest(p: vec3f, centres: array<vec3f, 4>) -> Hit {
  var d: vec3f;
  var distance: f32;
  var best: Hit = Hit(1000000000.0, i32(-(1)));
  for (var i: i32 = 0; i < 4; i = i + 1) {
    d = (centres[i] - p);
    distance = sqrt(dot(d, d));
    if ((distance < best.distance)) {
      best = Hit(distance, i);
    }
  }
  return best;
}
"""
    )


def test_inline_init_requires_the_inline_contract_on_the_class():
    source = """
from pyjs import js
from pyjs.shader import i32

@js
class Box:
    @js.inline("({x})")
    def __init__(self, x: i32): ...

@js
def main() -> Box:
    return Box(3)
"""
    with pytest.raises(CompilationError, match="inline __init__ method"):
        compile_source(source, filename="box.py")


def test_scalar_function_signature_and_body():
    out = emit("""
@wgsl
def scale(x: f32, k: f32) -> f32:
    return x * k
""")
    assert "fn scale(x: f32, k: f32) -> f32 {" in out
    assert "return (x * k);" in out


def test_int_annotations_choose_the_wgsl_type():
    out = emit("""
from pyjs.shader import u32

@wgsl
def h(x: u32) -> u32:
    return x * 3

@wgsl
def idx(x: i32) -> i32:
    return x - 1
""")
    assert "fn h(x: u32) -> u32" in out
    assert "fn idx(x: i32) -> i32" in out


@pytest.mark.parametrize(
    ("type_name", "shader_type"),
    (("int32", "i32"), ("uint32", "u32"), ("float32", "f32")),
)
def test_portable_numeric_formats_are_not_wgsl_types(
    type_name: str,
    shader_type: str,
):
    with pytest.raises(CompilationError) as caught:
        emit(f"""
from pyjs import {type_name}

@wgsl
def sample(value: {type_name}) -> {type_name}:
    return value
""")
    assert format_compilation_error(caught.value) == (
        '  File "_pyjs_wgsl_.py", line 6\n'
        f"    def sample(value: {type_name}) -> {type_name}:\n"
        f"{' ' * (27 + len(type_name))}{'^' * len(type_name)}\n"
        f"pyjs.CompilationError: portable PyJS {type_name} cannot compile "
        "for WGSL [PYJS1104]\n"
        f"help: Use pyjs.shader.{shader_type}.\n"
    )


def test_python_numeric_annotations_are_not_wgsl_types():
    with pytest.raises(CompilationError) as caught:
        emit("""
@wgsl
def sample(value: int) -> int:
    return value
""")

    assert format_compilation_error(caught.value) == (
        '  File "_pyjs_wgsl_.py", line 5\n'
        "    def sample(value: int) -> int:\n"
        "                              ^^^\n"
        "pyjs.CompilationError: Python int annotations cannot compile for "
        "WGSL [PYJS1104]\n"
        "help: Use pyjs.shader.i32 for shader numeric values.\n"
    )


@pytest.mark.parametrize(
    "type_name",
    [
        "int8",
        "int64",
        "float64",
    ],
)
def test_unsupported_shared_numeric_formats_have_focused_wgsl_errors(
    type_name: str,
):
    with pytest.raises(CompilationError) as caught:
        emit(f"""
from pyjs import {type_name}

@wgsl
def sample(value: {type_name}) -> {type_name}:
    return value
""")
    assert format_compilation_error(caught.value) == (
        '  File "_pyjs_wgsl_.py", line 6\n'
        f"    def sample(value: {type_name}) -> {type_name}:\n"
        f"{' ' * (27 + len(type_name))}{'^' * len(type_name)}\n"
        f"pyjs.CompilationError: portable PyJS {type_name} cannot compile "
        "for WGSL [PYJS1104]\n"
        "help: Use a WGSL-specific scalar type.\n"
    )


def test_integer_literals_are_unsuffixed():
    out = emit("""
from pyjs.shader import i32, u32

@wgsl
def mix(salt: u32, x: f32) -> u32:
    return u32(i32(x) + 1048576) * 83492791
""")
    assert "1048576u" not in out and "1048576" in out
    assert "83492791u" not in out


def test_float_literals_always_carry_a_point():
    out = emit("""
@wgsl
def f(x: f32) -> f32:
    return x * 2.0 + 1.0
""")
    assert "2.0" in out and "1.0" in out


@pytest.mark.parametrize("value", ["float('inf')", "float('nan')", "1e100"])
def test_non_f32_literals_are_refused(value: str):
    with pytest.raises(WGSLUnsupported, match="floating-point"):
        emit(f"""
from pyjs import JS

VALUE: JS = {value}

@wgsl
def constant() -> f32:
    return VALUE
""")


def test_native_functions_are_called_but_not_emitted():
    out = emit("""
@wgsl.native
def u32(x: i32) -> i32:
    return x & 0xFFFFFFFF

@wgsl
def wrap(x: i32) -> i32:
    return u32(x * 7)
""")
    assert "fn u32(" not in out, "the builtin cast was shadowed by an emitted function"
    assert "u32((x * 7))" in out


NATIVE_WITH_CLIENT_BODY = """
from pyjs import js, wgsl
from pyjs.shader import i32

@wgsl.native
def u32(x: i32) -> i32:
    return x & 0xFFFFFFFF

@js.inline("(Math.imul({a}, {b}) >>> 0)")
@wgsl.inline("({a} * {b})")
def mul32(a: i32, b: i32) -> i32:
    return (a * b) & 0xFFFFFFFF

@wgsl
def scramble(x: i32) -> i32:
    return u32(mul32(x, 7))

@js
def main() -> i32:
    return scramble(1)
"""


def test_native_bodies_are_compiled_for_the_client():
    js = compile_source(NATIVE_WITH_CLIENT_BODY, filename="native.py").sources["native"]
    assert "function u32(x)" in js
    assert "4294967295" in js, "the mask body did not reach the client"


def test_native_inline_is_chosen_per_backend():
    js = compile_source(NATIVE_WITH_CLIENT_BODY, filename="native.py").sources["native"]
    assert "Math.imul(x, (7 | 0))" in js
    assert "mul32(" not in js.split("function scramble")[1]
    out = transpile_wgsl(NATIVE_WITH_CLIENT_BODY)
    assert "u32((x * 7))" in out
    assert "imul" not in out and "fn mul32(" not in out


def test_shadowing_a_conversion_is_refused():
    with pytest.raises(WGSLUnsupported) as exc:
        emit("""
@wgsl
def u32(x: i32) -> i32:
    return x
""")
    assert (
        "wgsl.native" in str(exc.value)
        or "@wgsl.native" in str(exc.value)
        or "native" in str(exc.value)
    )


def test_control_flow():
    out = emit("""
@wgsl
def clamp01(x: f32) -> f32:
    t = x
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    else:
        t = t
    return t
""")
    assert "if ((t < 0.0)) {" in out
    assert "} else {" in out


def test_for_range_becomes_a_counted_loop():
    out = emit("""
@wgsl
def total(n: i32) -> f32:
    s = 0.0
    for i in range(n):
        s = s + 1.0
    return s
""")
    assert "let _pyjs_range_stop_0: i32 = n;" in out
    assert "for (var i: i32 = 0; i < _pyjs_range_stop_0; i = i + 1) {" in out


def test_descending_range_uses_the_negative_step_condition():
    out = emit("""
@wgsl
def total() -> i32:
    s = 0
    for i in range(3, 0, -1):
        s = s + i
    return s
""")
    assert "for (var i: i32 = 3; i > 0; i = i + -(1)) {" in out


@pytest.mark.parametrize("step", ["0", "True", "step"])
def test_range_requires_a_nonzero_literal_step(step: str):
    parameter = "step: i32" if step == "step" else ""
    with pytest.raises(WGSLUnsupported) as exc:
        emit(f"""
@wgsl
def total({parameter}) -> i32:
    s = 0
    for i in range(0, 3, {step}):
        s = s + i
    return s
""")
    assert "step" in str(exc.value)


def test_range_bounds_are_not_reevaluated_inside_the_wgsl_loop():
    assert (
        emit("""
@wgsl
def limit(stop: i32) -> i32:
    return stop + 1

@wgsl
def total(stop: i32) -> i32:
    value = 0
    bound = limit(stop)
    for index in range(bound):
        value += index
        bound = 0
    return value
""")
        == """\
fn limit(stop: i32) -> i32 {
  return (stop + 1);
}

fn total(stop: i32) -> i32 {
  var value: i32 = 0;
  var bound: i32 = limit(stop);
  let _pyjs_range_stop_0: i32 = bound;
  for (var index: i32 = 0; index < _pyjs_range_stop_0; index = index + 1) {
    value = (value + index);
    bound = 0;
  }
  return value;
}
"""
    )


def test_range_bound_temporary_does_not_shadow_a_python_local():
    assert (
        emit("""
@wgsl
def total(stop: i32) -> i32:
    _pyjs_range_stop_0 = 7
    bound = stop
    for index in range(bound):
        bound = 0
    return _pyjs_range_stop_0
""")
        == """\
fn total(stop: i32) -> i32 {
  var _pyjs_range_stop_0: i32 = 7;
  var bound: i32 = stop;
  let _pyjs_range_stop_1: i32 = bound;
  for (var index: i32 = 0; index < _pyjs_range_stop_1; index = index + 1) {
    bound = 0;
  }
  return _pyjs_range_stop_0;
}
"""
    )


def test_range_bound_expressions_keep_python_evaluation_order():
    assert (
        emit("""
@wgsl
def first(value: i32) -> i32:
    return value

@wgsl
def last(value: i32) -> i32:
    return value

@wgsl
def total(start: i32, stop: i32) -> i32:
    value = 0
    for index in range(first(start), last(stop)):
        value += index
    return value
""")
        == """\
fn first(value: i32) -> i32 {
  return value;
}

fn last(value: i32) -> i32 {
  return value;
}

fn total(start: i32, stop: i32) -> i32 {
  var value: i32 = 0;
  let _pyjs_range_start_0: i32 = first(start);
  let _pyjs_range_stop_1: i32 = last(stop);
  for (var index: i32 = _pyjs_range_start_0; index < _pyjs_range_stop_1; index = index + 1) {
    value = (value + index);
  }
  return value;
}
"""
    )


def test_iterating_anything_else_is_refused():
    with pytest.raises(WGSLUnsupported) as exc:
        emit("""
@wgsl
def f(n: i32) -> f32:
    s = 0.0
    for i in [1, 2, 3]:
        s = s + 1.0
    return s
""")
    assert "range" in str(exc.value)


@pytest.mark.parametrize(
    "statement",
    ["value = 1", "value += 1", "for value in range(2):\n        pass"],
)
def test_wgsl_function_parameters_cannot_be_assigned(statement: str):
    with pytest.raises(WGSLUnsupported, match="parameter 'value' is immutable"):
        emit(f"""
@wgsl
def changed(value: i32) -> i32:
    {statement}
    return value
""")


def test_unsupported_constructs_name_the_line():
    with pytest.raises(WGSLUnsupported) as exc:
        emit("""
@wgsl
def f(x: f32) -> f32:
    s = "no strings in a shader"
    return x
""")
    assert "line" in str(exc.value)


def test_calling_an_unmarked_function_is_refused():
    with pytest.raises(CompilationError) as exc:
        emit("""
def helper(x: f32) -> f32:
    return x

@wgsl
def f(x: f32) -> f32:
    return helper(x)
""")
    assert "not available to client code" in str(exc.value)


def test_math_builtins_map_through():
    out = emit("""
import math
from math import exp

@wgsl
def dist(x: f32, y: f32) -> f32:
    return math.sqrt(x * x + y * y) + exp(x)
""")
    assert "sqrt(" in out and "exp(x)" in out


def test_math_fmod_is_the_float_operator():
    out = emit("""
import math

@wgsl
def wrap(x: f32) -> f32:
    return math.fmod(x, 6.28)
""")
    assert "return f32((x % 6.28));" in out


def test_a_module_with_nothing_marked_is_an_error():
    with pytest.raises(WGSLUnsupported):
        emit("""
def plain(x: f32) -> f32:
    return x
""")


def test_structs_are_declared_and_constructed_positionally():
    out = emit("""
@wgsl
class Hit:
    distance: f32
    index: i32

    def __init__(self, distance: f32, index: i32) -> None:
        self.distance = distance
        self.index = index

@wgsl
def probe(x: f32) -> Hit:
    return Hit(x * 2.0, 3)

@wgsl
def distance_of(x: f32) -> f32:
    h = probe(x)
    return h.distance
""")
    assert "struct Hit {" in out
    assert "  distance: f32," in out and "  index: i32," in out
    assert out.index("struct Hit") < out.index("fn probe")
    assert "return Hit((x * 2.0), 3);" in out
    assert "var h: Hit = probe(x);" in out


def test_a_struct_with_no_annotated_fields_is_refused():
    with pytest.raises(WGSLUnsupported) as exc:
        emit("""
@wgsl
class Bare:
    def __init__(self, a: f32) -> None:
        self.a = a

@wgsl
def f(x: f32) -> Bare:
    return Bare(x)
""")
    assert "annotated fields" in str(exc.value)


def test_recursive_struct_layouts_are_refused():
    with pytest.raises(
        WGSLUnsupported,
        match="struct 'Node' is recursively defined",
    ):
        emit("""
@wgsl
class Node:
    child: Node

    def __init__(self, child: Node) -> None:
        self.child = child

@wgsl
def identity(node: Node) -> Node:
    return node
""")


def test_vector_types_map_to_their_wgsl_equivalents():
    out = emit("""
from pyjs.shader import vec3f, dot, length

@wgsl
def sd_capsule(p: vec3f, a: vec3f, b: vec3f, r: f32) -> f32:
    pa = p - a
    ba = b - a
    h = min(max(dot(pa, ba) / dot(ba, ba), 0.0), 1.0)
    return length(pa - ba * h) - r
""")
    assert "fn sd_capsule(p: vec3f, a: vec3f, b: vec3f, r: f32) -> f32" in out
    assert "var pa: vec3f = (p - a);" in out
    assert "dot(pa, ba)" in out and "length(" in out
    assert "class vec3f" not in out and "fn dot" not in out


def test_vector_equality_is_value_equality_in_python_and_wgsl():
    from pyjs.shader import vec2f, vec3f, vec4f

    for cls, values in (
        (vec2f, (1.0, 2.0)),
        (vec3f, (1.0, 2.0, 3.0)),
        (vec4f, (1.0, 2.0, 3.0, 4.0)),
    ):
        first = cls(*values)
        assert first == cls(*values)
        assert first != cls(*values[:-1], values[-1] + 1.0)
        assert first != object()

    assert (
        emit("""
from pyjs.shader import vec3f

@wgsl
def equal(left: vec3f, right: vec3f) -> bool:
    return left == right

@wgsl
def different(left: vec3f, right: vec3f) -> bool:
    return left != right
""")
        == """\
fn equal(left: vec3f, right: vec3f) -> bool {
  return all(left == right);
}

fn different(left: vec3f, right: vec3f) -> bool {
  return any(left != right);
}
"""
    )

    client = compile_source(
        """
from pyjs import js
from pyjs.shader import vec3f

@js
def main() -> bool:
    return vec3f(1.0, 2.0, 3.0) == vec3f(1.0, 2.0, 3.0)
""",
        filename="vector_equality.py",
    )
    assert (
        client.sources["vector_equality"]
        == """\
import { vec3f } from './pyjs.shader.js';

export function main() {
    return new vec3f(Math.fround(1.0), Math.fround(2.0), Math.fround(3.0)).__eq__(new vec3f(Math.fround(1.0), Math.fround(2.0), Math.fround(3.0)));
}"""
    )
    assert (
        client.sources["pyjs.shader"]
        == """\
export class vec3f {

    constructor(x, y, z) {
        this.x = Math.fround(x);
        this.y = Math.fround(y);
        this.z = Math.fround(z);
    }

    __eq__(other) {
        return (other instanceof vec3f) && this.x == other.x && (this.y == other.y) && (this.z == other.z);
    }
}"""
    )


def test_vector_equality_evaluates_each_operand_once():
    assert (
        emit("""
from pyjs.shader import vec3f

@wgsl
def make(value: f32) -> vec3f:
    return vec3f(value, value, value)

@wgsl
def equal(value: f32) -> bool:
    return make(value) == make(value)
""")
        == """\
fn make(value: f32) -> vec3f {
  return vec3f(value, value, value);
}

fn equal(value: f32) -> bool {
  return all(make(value) == make(value));
}
"""
    )


def test_struct_equality_is_recursive_dataclass_value_equality():
    assert (
        emit("""
from dataclasses import dataclass
from pyjs.shader import vec3f

@wgsl
@dataclass
class Point:
    position: vec3f
    weight: f32

@wgsl
@dataclass
class Segment:
    start: Point
    end: Point

@wgsl
def equal(left: Segment, right: Segment) -> bool:
    return left == right

@wgsl
def different(left: Segment, right: Segment) -> bool:
    return left != right
""")
        == """\
struct Point {
  position: vec3f,
  weight: f32,
}

struct Segment {
  start: Point,
  end: Point,
}

fn _pyjs_equal_Point(left: Point, right: Point) -> bool {
  return all(left.position == right.position) && (left.weight == right.weight);
}

fn _pyjs_equal_Segment(left: Segment, right: Segment) -> bool {
  return _pyjs_equal_Point(left.start, right.start) && _pyjs_equal_Point(left.end, right.end);
}

fn equal(left: Segment, right: Segment) -> bool {
  return _pyjs_equal_Segment(left, right);
}

fn different(left: Segment, right: Segment) -> bool {
  return !(_pyjs_equal_Segment(left, right));
}
"""
    )


def test_plain_structs_retain_python_identity_equality():
    with pytest.raises(WGSLUnsupported, match="uses Python identity equality"):
        emit("""
@wgsl
class Point:
    x: f32

    def __init__(self, x: f32) -> None:
        self.x = x

@wgsl
def equal(left: Point, right: Point) -> bool:
    return left == right
""")


def test_struct_equality_honors_dataclass_compare_fields():
    assert (
        emit("""
from dataclasses import dataclass, field

@wgsl
@dataclass
class Sample:
    value: i32
    ignored: i32 = field(compare=False)

@wgsl
def equal(left: Sample, right: Sample) -> bool:
    return left == right
""")
        == """\
struct Sample {
  value: i32,
  ignored: i32,
}

fn _pyjs_equal_Sample(left: Sample, right: Sample) -> bool {
  return (left.value == right.value);
}

fn equal(left: Sample, right: Sample) -> bool {
  return _pyjs_equal_Sample(left, right);
}
"""
    )


def test_struct_equality_helper_names_cannot_collide():
    with pytest.raises(
        WGSLUnsupported,
        match="_pyjs_equal_Point.*helper this backend generates",
    ):
        emit("""
from dataclasses import dataclass

@wgsl
@dataclass
class Point:
    x: f32

@wgsl
def _pyjs_equal_Point(left: Point, right: Point) -> bool:
    return True

@wgsl
def equal(left: Point, right: Point) -> bool:
    return left == right
""")


def test_vector_construction_and_components():
    out = emit("""
from pyjs.shader import vec3f, vec4f

@wgsl
def axis(q: vec4f) -> vec3f:
    return vec3f(q.x, q.y, q.z)
""")
    assert "-> vec3f" in out
    assert "return vec3f(q.x, q.y, q.z);" in out


def test_an_unmarked_type_says_what_is_missing():

    with pytest.raises(WGSLUnsupported) as exc:
        emit("""
@wgsl
def f(x: f32) -> str:
    return "shaders have no strings"
""")
    message = str(exc.value)
    assert "no WGSL type for 'str'" in message
    assert "@wgsl" in message and "@wgsl.native" in message


def test_reached_functions_are_emitted_from_any_module(package):
    name = package(
        {
            "a": """
from pyjs import js, wgsl

@js
def browser_only(value):
    return value.upper()

@wgsl
def shared(x: f32) -> f32:
    return x * 2.0

@wgsl
def helper(x: f32) -> f32:
    return shared(x) + 1.0
""",
        }
    )
    out = transpile_wgsl(f"""
from {name}.a import helper
from pyjs import wgsl
from pyjs.shader import f32

@wgsl
def entry(x: f32) -> f32:
    return helper(x)
""")
    assert "fn shared(" in out and "fn helper(" in out and "fn entry(" in out
    assert out.index("fn shared(") < out.index("fn helper(") < out.index("fn entry(")


def test_reserved_and_generated_names_are_protected_everywhere(package):
    name = package.name
    package(
        {
            "c": "from pyjs import wgsl\n\n@wgsl\ndef u32(x: i32) -> i32:\n    return x\n",
            "a": f"from pyjs import wgsl\nfrom {name}.c import u32\n\n"
            "@wgsl\ndef via_cast(x: i32) -> i32:\n    return u32(x)\n",
        }
    )
    with pytest.raises(WGSLUnsupported, match="names a WGSL conversion"):
        transpile_wgsl(
            f"from {name}.a import via_cast\nfrom pyjs import wgsl\n"
            "from pyjs.shader import i32\n\n"
            "@wgsl\ndef entry(x: i32) -> i32:\n    return via_cast(x)\n"
        )


def test_two_definitions_of_one_name_are_refused(package):
    name = package(
        {
            "a": "from pyjs import wgsl\n\n@wgsl\ndef shared(x: f32) -> f32:\n    return x * 2.0\n",
            "b": "from pyjs import wgsl\n\n@wgsl\ndef shared(x: f32) -> f32:\n    return x * 3.0\n",
        }
    )
    with pytest.raises(WGSLUnsupported) as exc:
        transpile_wgsl(f"""
from {name}.a import shared as a_shared
from {name}.b import shared as b_shared
from pyjs import wgsl
from pyjs.shader import f32

@wgsl
def both(x: f32) -> f32:
    return a_shared(x) + b_shared(x)
""")
    assert f"{name}.a.shared" in str(exc.value) and f"{name}.b.shared" in str(exc.value)


def test_types_are_found_where_they_were_imported_from():
    out = emit("""
from pyjs.shader import vec3f

@wgsl
def scale(v: vec3f, k: f32) -> vec3f:
    return v * k
""")
    assert "fn scale(v: vec3f, k: f32) -> vec3f" in out


def test_a_local_first_assigned_in_a_branch_is_declared_at_function_scope():
    out = emit("""
@wgsl
def pick(x: f32) -> f32:
    if x < 0.0:
        d = -x
    else:
        d = x * 2.0
    return d
""")
    lines = [line.strip() for line in out.splitlines()]
    assert "var d: f32;" in lines, "the local was not hoisted out of the branches"
    assert "d = -(x);" in lines
    assert "d = (x * 2.0);" in lines
    assert lines.index("var d: f32;") < lines.index("d = -(x);")


def test_unary_operators_survive_the_analyzer_rewrite():
    out = emit("""
@wgsl
def f(x: f32) -> f32:
    return abs(x) + -x
""")
    assert "abs(x)" in out
    assert "-(x)" in out


def test_chained_assignment_temporaries_are_valid_and_collision_safe():
    out = emit("""
@wgsl
def chain(flag: bool) -> i32:
    _pyjs_local_0 = i32(5)
    if flag:
        first = second = i32(1)
    else:
        first = second = i32(2)
    return first + second + _pyjs_local_0
""")
    assert out.strip() == """fn chain(flag: bool) -> i32 {
  var _pyjs_local_1: i32;
  var first: i32;
  var second: i32;
  var _pyjs_local_2: i32;
  var _pyjs_local_0: i32 = i32(5);
  if (flag) {
    _pyjs_local_1 = i32(1);
    first = _pyjs_local_1;
    second = _pyjs_local_1;
  } else {
    _pyjs_local_2 = i32(2);
    first = _pyjs_local_2;
    second = _pyjs_local_2;
  }
  return ((first + second) + _pyjs_local_0);
}"""


def test_array_parameters_take_their_length_from_the_annotation():
    out = emit("""
from typing import Annotated

@wgsl
class Item:
    value: f32

    def __init__(self, value: f32) -> None:
        self.value = value

@wgsl
def total(items: Array[Item, 4]) -> f32:
    s = 0.0
    for i in range(4):
        s = s + items[i].value
    return s
""")
    assert "fn total(items: array<Item, 4>) -> f32" in out
    assert "items[i].value" in out
    assert "get_list_item" not in out


def test_nested_shader_arrays_preserve_each_wgsl_dimension():
    assert (
        emit("""
@wgsl
def corner(values: Array[Array[f32, 2], 3]) -> f32:
    return values[2][1]
""")
        == """\
fn corner(values: array<array<f32, 2>, 3>) -> f32 {
  return values[2][1];
}
"""
    )


def test_portable_static_arrays_are_not_shader_arrays():
    with pytest.raises(
        CompilationError,
        match="portable array types cannot compile for wgsl",
    ):
        emit("""
from pyjs import StaticArray

@wgsl
def first(values: StaticArray[f32, 2]) -> f32:
    return values[0]
""")


@pytest.mark.parametrize(
    ("length", "complaint"),
    [
        ("True", "compile-time integer"),
        ("'four'", "compile-time integer"),
        ("0", "positive"),
        ("-1", "positive"),
        ("2, 3", "item type and length"),
    ],
)
def test_array_lengths_must_be_one_positive_integer(length: str, complaint: str):
    with pytest.raises(CompilationError, match=complaint):
        emit(f"""
from typing import Annotated

@wgsl
def total(items: Array[f32, {length}]) -> f32:
    return items[0]
""")


def test_unannotated_wgsl_return_uses_the_inferred_type():
    assert (
        emit(
            """
@wgsl
def scale(x: f32, k: f32):
    return x * k
"""
        )
        == """\
fn scale(x: f32, k: f32) -> f32 {
  return (x * k);
}
"""
    )


def test_array_lengths_are_read_from_the_evaluated_annotation():
    out = emit("""
from typing import Annotated
from pyjs import JS

MAX_ITEMS: JS = 4
type Pair = Array[f32, 2]

@wgsl
def total(items: Array[f32, MAX_ITEMS], pair: Pair) -> f32:
    return items[3] + pair[1]
""")
    assert "fn total(items: array<f32, 4>, pair: array<f32, 2>) -> f32" in out


def test_annotated_metadata_on_scalars_is_not_a_length():
    out = emit("""
from typing import Annotated

@wgsl
def scale(x: Annotated[f32, 1, 2], k: Annotated[i32, "gain", 0]) -> Annotated[f32, 3]:
    return x * f32(k)
""")
    assert "fn scale(x: f32, k: i32) -> f32" in out


def test_a_list_parameter_without_a_length_says_how_to_give_one():
    with pytest.raises(WGSLUnsupported) as exc:
        emit("""
@wgsl
class Item:
    value: f32

    def __init__(self, value: f32) -> None:
        self.value = value

@wgsl
def total(items: list[Item]) -> f32:
    return items[0].value
""")
    assert "Array[T, N]" in str(exc.value)


def test_inline_natives_emit_an_operator():
    out = emit("""
@wgsl.inline("({a} % {b})")
def fmod(a: f32, b: f32) -> f32:
    return a - b * f32(i32(a / b))

@wgsl
def wrap(x: f32) -> f32:
    return fmod(x, 6.28)
""")
    assert "(x % 6.28)" in out
    assert "fn fmod(" not in out


def test_wgsl_roots_are_separate_from_javascript_reachability():
    src = """
from pyjs import js, wgsl
from pyjs.shader import f32, i32

@wgsl
def helper(x: f32) -> f32:
    return x * 2.0

@wgsl.native
def u32(x: i32) -> i32:
    return x & 0xFFFFFFFF

@wgsl
def clamp0(a: f32) -> f32:
    return max(helper(a), 0.0)

@wgsl
def scramble(x: i32) -> i32:
    return u32(x * 7)

@js
def main() -> f32:
    return 1.0
"""
    js = compile_source(src, filename="kept.py").sources["kept"]
    assert "function clamp0(" not in js and "function scramble(" not in js
    assert "function helper(" not in js and "function u32(" not in js

    out = transpile_wgsl(src)
    assert "fn helper(" in out and "fn clamp0(" in out and "fn scramble(" in out
    assert "max(helper(a), 0.0)" in out and "u32((x * 7))" in out


def test_wgsl_does_not_analyze_unrelated_javascript_definitions():
    source = """
from pyjs import js, wgsl
from pyjs.shader import f32

@js
def browser_only(value):
    return value.upper()

@wgsl
def scale(value: f32) -> f32:
    return value * 2.0
"""
    assert (
        transpile_wgsl(source)
        == """\
fn scale(value: f32) -> f32 {
  return (value * 2.0);
}
"""
    )
    with pytest.raises(CompilationError, match="requires a type annotation"):
        compile_source(source)


def test_wgsl_does_not_build_unrelated_javascript_classes():
    source = """
from pyjs import js, wgsl
from pyjs.shader import f32
from pyjs.web.html import HTMLDivElement

@js
class BrowserOnly(HTMLDivElement):
    def __init__(self):
        super().__init__()

@wgsl
def scale(value: f32) -> f32:
    return value * 2.0
"""
    assert (
        transpile_wgsl(source)
        == """\
fn scale(value: f32) -> f32 {
  return (value * 2.0);
}
"""
    )


def test_wgsl_native_and_inline_cpu_bodies_are_not_analyzed_for_wgsl():
    assert (
        emit("""
@wgsl.native
def native_lookup(value: f32) -> f32:
    values = {"value": value}
    return values["value"]

@wgsl.inline("({value})")
def inline_lookup(value: f32) -> f32:
    values = {"value": value}
    return values["value"]

@wgsl
def calculate(value: f32) -> f32:
    return native_lookup(value) + inline_lookup(value)
""")
        == """\
fn calculate(value: f32) -> f32 {
  return (native_lookup(value) + (value));
}
"""
    )


def test_wgsl_rejects_operations_absent_from_its_python_surface():
    with pytest.raises(CompilationError, match="'upper' is not defined on 'str'"):
        emit("""
@wgsl
def capitalize(value: str) -> str:
    return value.upper()
""")


def test_wgsl_semantics_do_not_leak_into_later_javascript_analysis():
    transpile_wgsl("""
from pyjs import wgsl
from pyjs.shader import f32

@wgsl
def scale(value: f32) -> f32:
    return value * 2.0
""")
    compiled = compile_source("""
from pyjs import js

@js
def main(value: str) -> str:
    return value.upper()
""")
    assert (
        compiled.sources["_pyjs_source_"]
        == """\
export function main(value) {
    return value.toUpperCase();
}"""
    )


@pytest.mark.parametrize(
    ("body", "complaint"),
    [
        (
            "def f(a: i32, b: f32) -> bool:\n    return a < b",
            "different fixed-width numeric",
        ),
        (
            "def f(a: i32, b: f32) -> f32:\n    return a + b",
            "different fixed-width numeric",
        ),
        ("def f(a: i32) -> f32:\n    return a + 1.0", "does not mix"),
        ("def f(a: i32, n: i32) -> i32:\n    return a >> n", "shift count is u32"),
        ("def f(a: bool) -> bool:\n    return a == 1", "cannot be used as bool"),
        ("def f(a: i32) -> i32:\n    return a + 4294967295", "represented as i32"),
        ("def f(a: i32) -> i32:\n    return a >> -1", "represented as u32"),
        ("def f(a: i32) -> i32:\n    return a >> 32", "between 0 and 31"),
    ],
)
def test_expressions_wgsl_would_not_type_check_are_refused(body: str, complaint: str):
    with pytest.raises((CompilationError, WGSLUnsupported), match=complaint):
        emit("@wgsl\n" + body)


def test_expressions_wgsl_accepts_pass_through():
    out = emit("""
import math
from pyjs.shader import vec3f, u32

@wgsl
def f(a: i32, b: i32, x: f32, v: vec3f, h: u32) -> f32:
    ratio = f32(a) / f32(b)
    scaled = v * x
    shifted = h >> 8
    whole = math.floor(x)
    return ratio + x + 1 + scaled.x + f32(shifted) + f32(whole)
""")
    assert "var ratio: f32 = (f32(a) / f32(b));" in out
    assert "var scaled: vec3f = (v * x);" in out
    assert "var shifted: u32 = (h >> 8);" in out
    assert "var whole: i32 = i32(floor(x));" in out


def test_abstract_int_must_fit_a_concrete_u32_operand():
    with pytest.raises((CompilationError, WGSLUnsupported), match="represented as u32"):
        emit("""
from pyjs.shader import u32

@wgsl
def decrement(value: u32) -> u32:
    return value + -1
""")

    with pytest.raises((CompilationError, WGSLUnsupported), match="represented as u32"):
        emit("""
from pyjs.shader import u32

@wgsl
def overflow(value: u32) -> u32:
    return value + 4294967296
""")


def test_integer_literal_boundaries_are_accepted():
    out = emit("""
from pyjs.shader import u32

@wgsl
def boundaries(signed: i32, unsigned: u32) -> u32:
    low = signed + -2147483648
    high = low + 2147483647
    return unsigned + 4294967295
""")
    assert "(signed + -(2147483648))" in out
    assert "(low + 2147483647)" in out
    assert "(unsigned + 4294967295)" in out

    shifted = emit("""
from pyjs.shader import u32

@wgsl
def highest_shift(value: u32) -> u32:
    return value >> 31
""")
    assert "return (value >> 31);" in shifted


def test_contextual_hash_literals_use_contextual_u32_arithmetic():
    assert (
        transpile_wgsl("""
from pyjs import wgsl
from pyjs.shader import f32, i32, u32

@wgsl
def integer_hash(cx: f32, cy: f32, salt: u32) -> f32:
    h = (
        u32(i32(cx) + 1048576) * 73856093
        ^ u32(i32(cy) + 1048576) * 19349663
        ^ salt * 83492791
    )
    h = h ^ (h >> 16)
    h = h * 2135587861
    h = h ^ (h >> 15)
    h = h * 2246822507
    h = h ^ (h >> 16)
    return f32(h >> 8) / 16777216.0
""")
        == """\
fn integer_hash(cx: f32, cy: f32, salt: u32) -> f32 {
  var h: u32 = (((u32((i32(cx) + 1048576)) * 73856093) ^ (u32((i32(cy) + 1048576)) * 19349663)) ^ (salt * 83492791));
  h = (h ^ (h >> 16));
  h = (h * 2135587861);
  h = (h ^ (h >> 15));
  h = (h * 2246822507);
  h = (h ^ (h >> 16));
  return (f32((h >> 8)) / 16777216.0);
}
"""
    )


def test_integer_literals_must_fit_return_assignment_and_cast_contexts():
    for body in (
        "def f() -> i32:\n    return 4294967295",
        "def f() -> i32:\n    value: i32 = 4294967295\n    return value",
    ):
        source = "@wgsl\n" + body
        with pytest.raises(
            (CompilationError, WGSLUnsupported),
            match="represented as i32",
        ):
            emit(source)

    with pytest.raises(WGSLUnsupported, match="cannot be represented as i32 in WGSL"):
        emit("""
from pyjs.shader import i32

@wgsl
def signed() -> i32:
    return i32(4294967295)
""")
    with pytest.raises(WGSLUnsupported, match="cannot be represented as u32 in WGSL"):
        emit("""
from pyjs.shader import u32

@wgsl
def unsigned() -> u32:
    return u32(-1)
""")

    assert (
        emit("""
from pyjs.shader import i32, u32

@wgsl
def signed(value: u32) -> i32:
    return i32(value)
""")
        == """\
fn signed(value: u32) -> i32 {
  return i32(value);
}
"""
    )


def test_assignments_and_returns_require_the_declared_wgsl_type():
    for body in (
        "return value",
        "result: i32 = value\n    return result",
    ):
        with pytest.raises(
            CompilationError,
            match="different fixed-width numeric types cannot be assigned",
        ):
            emit(f"""
from pyjs.shader import u32

@wgsl
def signed(value: u32) -> i32:
    {body}
""")


def test_unsigned_unary_results_are_not_silently_retyped():
    with pytest.raises(
        CompilationError,
        match="different fixed-width numeric types cannot be assigned",
    ):
        emit("""
from pyjs.shader import u32

@wgsl
def signed(value: u32) -> i32:
    return ~value
""")


@pytest.mark.parametrize("operator", ["-", "&", "%"])
def test_unsigned_binary_results_are_not_silently_retyped(operator: str):
    with pytest.raises(
        CompilationError,
        match="different fixed-width numeric types cannot be assigned",
    ):
        emit(f"""
from pyjs.shader import u32

@wgsl
def signed(left: u32, right: u32) -> i32:
    return left {operator} right
""")


def test_scalar_conversions_share_python_truthiness_semantics():
    assert (
        emit("""
@wgsl
def truth(value: i32) -> bool:
    return bool(value)
""")
        == """\
fn truth(value: i32) -> bool {
  return bool(value);
}
"""
    )


def test_wgsl_integer_division_and_remainder_use_native_operators():
    assert (
        emit("""
@wgsl
def integer_divide(left: i32, right: i32) -> i32:
    return left / right

@wgsl
def integer_mod(left: i32, right: i32) -> i32:
    return left % right

@wgsl
def float_mod(left: f32, right: f32) -> f32:
    return left % right
""")
        == """\
fn integer_divide(left: i32, right: i32) -> i32 {
  return (left / right);
}

fn integer_mod(left: i32, right: i32) -> i32 {
  return (left % right);
}

fn float_mod(left: f32, right: f32) -> f32 {
  return (left % right);
}
"""
    )


def test_conditional_expression_only_accepts_eager_safe_values():
    out = emit("""
@wgsl
def choose(x: f32, enabled: bool) -> f32:
    return x if enabled else 0.0
""")
    assert "return select(0.0, x, enabled);" in out

    with pytest.raises(WGSLUnsupported, match="if statement"):
        emit("""
@wgsl
def choose(x: f32, enabled: bool) -> f32:
    return abs(x) if enabled else 0.0
""")


def test_scalar_module_constants_are_inlined_into_the_shader():
    assert (
        emit("""
import math
from pyjs import JS

GAIN: JS = 2.0

@wgsl
def scale(x: f32) -> f32:
    return x * GAIN + math.pi
""")
        == """\
fn scale(x: f32) -> f32 {
  return ((x * 2.0) + 3.141592653589793);
}
"""
    )


@pytest.mark.parametrize(
    ("body", "complaint"),
    [
        (
            "def f(x: f32 = 1.0) -> f32:\n    return x",
            "default arguments",
        ),
        (
            "def f(*values: f32) -> f32:\n    return 0.0",
            "variadic parameters",
        ),
        (
            "def f(*, value: f32) -> f32:\n    return value",
            "keyword-only parameters",
        ),
        (
            "async def f(x: f32) -> f32:\n    return x",
            "cannot be async",
        ),
    ],
)
def test_function_signatures_must_have_a_wgsl_call_shape(
    body: str,
    complaint: str,
):
    with pytest.raises(WGSLUnsupported, match=complaint):
        emit("@wgsl\n" + body)


def test_calls_require_the_same_concrete_wgsl_parameter_type():
    with pytest.raises(
        CompilationError,
        match="different fixed-width numeric types cannot be assigned",
    ):
        emit("""
@wgsl
def scale(value: f32) -> f32:
    return value * 2.0

@wgsl
def apply(value: i32) -> f32:
    return scale(value)
""")

    assert (
        emit("""
@wgsl
def scale(value: f32) -> f32:
    return value * 2.0

@wgsl
def apply(value: i32) -> f32:
    return scale(f32(value))
""")
        == """\
fn scale(value: f32) -> f32 {
  return (value * 2.0);
}

fn apply(value: i32) -> f32 {
  return scale(f32(value));
}
"""
    )


def test_boolean_operators_do_not_adopt_python_operand_value_semantics():
    with pytest.raises(WGSLUnsupported, match="require bool operands"):
        emit("""
@wgsl
def choose(left: i32, right: i32) -> i32:
    return left and right
""")


def test_numeric_builtins_validate_literals_and_boolean_operands():
    assert (
        emit("""
@wgsl
def magnitude() -> i32:
    return abs(-1)
""")
        == """\
fn magnitude() -> i32 {
  return i32(abs(-(1)));
}
"""
    )

    with pytest.raises(WGSLUnsupported, match="does not accept bool"):
        emit("""
@wgsl
def first(left: bool, right: bool) -> bool:
    return min(left, right)
""")

    with pytest.raises(WGSLUnsupported, match="represented as i32"):
        emit("""
@wgsl
def too_large(value: i32) -> i32:
    return min(value, 4294967295)
""")

    with pytest.raises(WGSLUnsupported, match="abs.*cannot be represented"):
        emit("""
@wgsl
def magnitude() -> i32:
    return abs(-2147483648)
""")


def test_multi_argument_min_and_max_become_nested_wgsl_calls():
    assert (
        emit("""
@wgsl
def extremes(a: i32, b: i32, c: i32) -> i32:
    return min(a, b, c) + max(a, b, c)
""")
        == """\
fn extremes(a: i32, b: i32, c: i32) -> i32 {
  return (min(min(a, b), c) + max(max(a, b), c));
}
"""
    )

    with pytest.raises(WGSLUnsupported, match="two or more scalar arguments"):
        emit("""
from typing import Annotated

@wgsl
def smallest(values: Array[i32, 2]) -> i32:
    return min(values)
""")


@pytest.mark.parametrize(
    ("index", "complaint"),
    [("-1", "negative-index"), ("2", "outside its length 2")],
)
def test_fixed_array_literal_indexes_are_checked(index: str, complaint: str):
    with pytest.raises(WGSLUnsupported, match=complaint):
        emit(f"""
from typing import Annotated

@wgsl
def item(values: Array[f32, 2]) -> f32:
    return values[{index}]
""")


def test_while_else_is_refused_instead_of_silently_dropped():
    with pytest.raises(WGSLUnsupported, match="while/else"):
        emit("""
@wgsl
def count(value: i32) -> i32:
    while value > 0:
        value = value - 1
    else:
        value = 3
    return value
""")


def test_loop_target_used_after_the_loop_is_hoisted():
    assert (
        emit("""
@wgsl
def last() -> i32:
    for index in range(3):
        pass
    return index
""")
        == """\
fn last() -> i32 {
  var index: i32;
  for (index = 0; index < 3; index = index + 1) {
  }
  return index;
}
"""
    )


def test_struct_constructor_cannot_hide_python_only_field_transforms():
    with pytest.raises(WGSLUnsupported, match="assign each parameter directly"):
        emit("""
@wgsl
class Point:
    x: f32

    def __init__(self, x: f32) -> None:
        self.x = x * 2.0

@wgsl
def point(x: f32) -> Point:
    return Point(x)
""")


def test_dataclass_is_a_valid_direct_struct_constructor():
    assert (
        emit("""
from dataclasses import dataclass

@wgsl
@dataclass
class Point:
    x: f32
    y: f32

@wgsl
def point(x: f32, y: f32) -> Point:
    return Point(x, y)
""")
        == """\
struct Point {
  x: f32,
  y: f32,
}

fn point(x: f32, y: f32) -> Point {
  return Point(x, y);
}
"""
    )


def test_dataclass_struct_cannot_transform_fields_after_construction():
    with pytest.raises(WGSLUnsupported, match="cannot use __post_init__"):
        emit("""
from dataclasses import dataclass

@wgsl
@dataclass
class Point:
    x: f32

    def __post_init__(self) -> None:
        self.x *= 2.0

@wgsl
def point(x: f32) -> Point:
    return Point(x)
""")


def test_fixed_array_calls_require_the_same_length():
    with pytest.raises(CompilationError, match="different static array types"):
        emit("""
from typing import Annotated

@wgsl
def first(values: Array[i32, 3]) -> i32:
    return values[0]

@wgsl
def wrong(values: Array[i32, 2]) -> i32:
    return first(values)
""")


def test_range_bounds_require_the_loop_variables_integer_type():
    with pytest.raises(WGSLUnsupported, match="bound is u32.*i32"):
        emit("""
from pyjs.shader import u32

@wgsl
def count(stop: u32) -> i32:
    total = 0
    for index in range(stop):
        total += index
    return total
""")


def test_bool_not_has_a_direct_wgsl_form():
    assert (
        emit("""
@wgsl
def invert(value: bool) -> bool:
    return not value
""")
        == """\
fn invert(value: bool) -> bool {
  return !(value);
}
"""
    )


def test_recursive_wgsl_call_graphs_are_refused():
    with pytest.raises(WGSLUnsupported, match="recursive call graph reaches 'even'"):
        emit("""
@wgsl
def even(value: i32) -> bool:
    if value == 0:
        return True
    return odd(value - 1)

@wgsl
def odd(value: i32) -> bool:
    if value == 0:
        return False
    return even(value - 1)
""")


def test_shader_types_have_bodies_on_the_client():
    src = """
from pyjs import js
from pyjs.shader import f32, vec3f, dot

@js
def main() -> f32:
    a = vec3f(1.0, 2.0, 3.0)
    b = a + a
    return dot(a, b)
"""
    js = compile_source(src, filename="v.py").sources["pyjs.shader"]
    ctor = js.split("class vec3f")[1].split("constructor(x, y, z) {")[1].split("}")[0]
    assert "this.x = Math.fround(x)" in ctor
    assert "this.z = Math.fround(z)" in ctor
    assert "__add__(other) {\n    }" not in js, "operator body missing"


def test_inline_target_type_constructor_needs_no_class_import():
    src = """
from pyjs import js
from pyjs.shader import u32

@js
def main() -> u32:
    return u32(7)
"""
    js = compile_source(src, filename="conversion.py").sources["conversion"]
    assert (
        js
        == """\
export function main() {
    return (7 >>> 0);
}"""
    )


def test_operator_results_are_instances():
    src = """
from pyjs import js
from pyjs.shader import f32, vec3f

@js
def main() -> f32:
    a = vec3f(1.0, 2.0, 3.0)
    return (a * 2.0).z + (-a).y + ((a + a) - a).x
    """
    js = compile_source(src, filename="ops.py").sources["ops"]
    assert (
        js
        == """\
import { vec3f } from './pyjs.shader.js';

export function main() {
    var a = new vec3f(Math.fround(1.0), Math.fround(2.0), Math.fround(3.0));
    return Math.fround(Math.fround(a.__mul__(Math.fround(2.0)).z + a.__neg__().y) + a.__add__(a).__sub__(a).x);
}"""
    )
