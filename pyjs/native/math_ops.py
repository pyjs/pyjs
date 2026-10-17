"""Adapt concrete Python calls to libm and the Python-authored math runtime."""

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.objects import UnionType

from . import calls, collection_ops, tagged
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported
from .runtime import math_algorithms


def declarations():
    unary = ("llvm.sqrt.f64", "llvm.sin.f64", "llvm.cos.f64", "llvm.log.f64",
             "llvm.log2.f64", "llvm.log10.f64", "llvm.exp.f64", "llvm.exp2.f64",
             "llvm.ceil.f64", "llvm.trunc.f64", "tan", "asin", "acos", "acosh",
             "atanh", "log1p", "asinh", "atan", "cbrt", "erf", "erfc", "tanh",
             "expm1", "cosh", "sinh", "tgamma", "lgamma")
    binary = ("atan2", "remainder", "nextafter", "pow")
    return [*math_algorithms.compiled_runtime(),
            *(f"declare double @{name}(double)" for name in unary),
            *(f"declare double @{name}(double, double)" for name in binary),
            "declare double @fma(double, double, double)",
            "declare double @ldexp(double, i32)",
            "declare double @frexp(double, ptr)",
            "declare double @modf(double, ptr)"]


def call(emitter, target, operation, node):
    if operation != "math.hypot" and calls.expands_arguments(node):
        raise LLVMUnsupported("native math argument unpacking requires statically known parameters", node)
    if operation == "math.fsum":
        return fsum(emitter, target, node)
    if operation in {"math.dist", "math.hypot"}:
        return norm(emitter, target, operation, node)
    with calls.bind(emitter, target, node) as bound:
        arguments = calls.convert(emitter, target, bound, node)
        if operation == "math.ldexp":
            exponent = emitter.emit_value(f"trunc i64 {arguments[1][1]} to i32")
            return "double", emitter.emit_value(f"call double @ldexp(double {arguments[0][1]}, i32 {exponent})")
        name = operation.removeprefix("math.")
        kind = "i32" if name == "frexp" else "double"
        slot = emitter.emit_value(f"alloca {kind}")
        emitter.emit_line(f"store {kind} {'0' if kind == 'i32' else '0.0'}, ptr {slot}")
        value = emitter.emit_value(f"call double @{name}(double {arguments[0][1]}, ptr {slot})")
        part = emitter.emit_value(f"load {kind}, ptr {slot}")
        if kind == "i32":
            part = emitter.emit_value(f"sext i32 {part} to i64")
            kind = "i64"
        return "ptr", collection_ops.new_tuple(emitter, target.return_type, [("double", value), (kind, part)])


def numeric_float(emitter, semantic, value, node):
    members = semantic.types if isinstance(semantic, UnionType) else (semantic,)
    if any(collection_ops.builtin_name(tagged.runtime_type(member)) not in {"bool", "int", "float"}
           for member in members):
        raise LLVMUnsupported("LLVM math aggregates require bool, int or float items, or their closed unions", node)
    if isinstance(semantic, UnionType):
        # All accepted tags have scalar payloads: bool is 0/1, int is signed
        # i64, float is binary64 bits. Use SSA conversion rather than a switch
        # result alloca inside an unbounded iterable-consumption loop.
        actual, bits = tagged.parts(emitter, value)
        integer = emitter.emit_value(f"sitofp i64 {bits} to double")
        floating = emitter.emit_value(f"bitcast i64 {bits} to double")
        is_float = emitter.emit_value(f"icmp eq i64 {actual}, {tagged.TAGS['float']}")
        return emitter.emit_value(f"select i1 {is_float}, double {floating}, double {integer}")
    kind = emitter.value_type(semantic)
    if kind == "i1":
        return emitter.emit_value(f"uitofp i1 {value} to double")
    return emitter.coerce_numeric(kind, value, "double", node)[1]


class Coordinates(calls.ExpandedCall):
    """hypot's numeric coercion uses the ordinary checked argument binder."""

    def convert(self, actual, representation, expected, declared, value):
        return "double", numeric_float(self.emitter, actual, value, self.node)


def norm(emitter, target, operation, node):
    arguments = (Coordinates(emitter, target, node).bind()
                 if operation == "math.hypot" and calls.expands_arguments(node)
                 else calls.bind(emitter, target, node))
    with arguments:
        if operation == "math.hypot":
            values = arguments.values[0][1]
        else:
            snapshots = []
            member = NATIVE_ENVIRONMENT.builtins.search("float")
            slots, frame = calls.value_slots(emitter, ["ptr", "ptr"])
            for source, (_, value), slot in zip(node.args, arguments.values, slots, strict=True):
                # dist snapshots all of p before q; zip-like advancement changes
                # observable generator effects and mismatched-length consumption.
                snapshot = collection_ops.new_list(emitter, member)
                emitter.emit_line(f"store ptr {snapshot}, ptr {slot}")

                def append(actual, item, snapshot=snapshot):
                    item = numeric_float(emitter, actual, item, node)
                    collection_ops.append(emitter, snapshot, member, member, item, node)

                collection_ops.loop(emitter, analyzed_value_type(source), value, append, node)
                snapshots.append(snapshot)
            values, right = snapshots
            length = emitter.emit_value(f"load i64, ptr {values}")
            other = emitter.emit_value(f"load i64, ptr {right}")
            emitter.guard_exception(node, emitter.emit_value(f"icmp eq i64 {length}, {other}"),
                                    "ValueError", "both points must have the same number of dimensions")
            left_data, right_data = [collection_ops.storage(emitter, snapshot, 2) for snapshot in snapshots]
            result = emitter.emit_value(
                f"call double @pyjs.math.distance(ptr {left_data}, ptr {right_data}, i64 {length})")
            calls.pop_roots(emitter, frame)
            return "double", result
        length = emitter.emit_value(f"load i64, ptr {values}")
        data = collection_ops.storage(emitter, values, 2)
        return "double", emitter.emit_value(f"call double @pyjs.math.norm(ptr {data}, i64 {length})")


def fsum(emitter, target, node):
    with calls.bind(emitter, target, node) as arguments:
        arena = emitter.load_local("__arena")
        partials = collection_ops.new_list(emitter, NATIVE_ENVIRONMENT.builtins.search("float"))
        frame = calls.root_values(emitter, partials)
        state = emitter.emit_value("alloca [2 x double]")
        emitter.emit_line(f"store [2 x double] zeroinitializer, ptr {state}")

        def consume(actual, value):
            value = numeric_float(emitter, actual, value, node)
            status = emitter.emit_value(
                f"call i64 @pyjs.fsum.add(ptr {arena}, ptr {partials}, ptr {state}, double {value})")
            emitter.guard_exception(node, emitter.emit_value(f"icmp ne i64 {status}, -1"),
                                    "MemoryError", "native collection allocation failed")
            emitter.guard_exception(node, emitter.emit_value(f"icmp ne i64 {status}, -2"),
                                    "OverflowError", "intermediate overflow in fsum")

        collection_ops.loop(emitter, analyzed_value_type(node.args[0]), arguments.values[0][1], consume, node)
        output = emitter.emit_value("alloca double")
        status = emitter.emit_value(f"call i64 @pyjs.fsum.finish(ptr {partials}, ptr {state}, ptr {output})")
        emitter.guard_exception(node, emitter.emit_value(f"icmp eq i64 {status}, 0"),
                                "ValueError", "-inf + inf in fsum")
        calls.pop_roots(emitter, frame)
        return "double", emitter.emit_value(f"load double, ptr {output}")
