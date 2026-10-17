"""Format mini-language parsing and ordinary checked application dispatch."""

import ast
import re

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.objects import Constant, Function
from pyjs.analysis.type_relations import is_subclass
from pyjs.python import native as builtins

from . import calls, collection_ops, enum_ops, nullable, representation, tagged
from .errors import LLVMUnsupported
from .output_ops import Buffer

SPEC = re.compile(r"(?:(.)([<>=^])|([<>=^]))?([+ -])?(#)?(0)?([0-9]+)?(?:\.([0-9]+))?([sbodxXeEfFgG%]?)", re.DOTALL)
# Recognize valid but unsupported features separately from malformed specs.
# Erased dispatch emits all candidate arms; an invalid builtin arm must raise
# only when selected, not prevent an unrelated custom __format__ from compiling.
# Python 3.14 also allows fractional grouping without precision (e.g. '._');
# a bare '.' is still malformed, so digits cannot simply become optional.
FORMAT_GRAMMAR = re.compile(r"(?:(.)[<>=^]|[<>=^])?[+ -]?z?#?0?[0-9]*[,_]?(?:\.(?:[0-9]+[,_]?|[,_]))?[bcdeEfFgGnosxX%]?", re.DOTALL)


def base_string(e, target, node):
    from .indexing import integer

    if len(node.args) != 1 or node.keywords or calls.expands_arguments(node):
        raise LLVMUnsupported(f"LLVM {target.name} takes one positional argument", node)
    source = node.args[0]
    kind, value = e.expression(source)
    value = integer(e, analyzed_value_type(source), kind, value, node)
    base = {builtins._bin: 2, builtins._oct: 8, builtins._hex: 16}[target.py_func]
    return "ptr", e.allocated_value(f"call ptr @pyjs.format.integer({collection_ops.owner(e)}, "
                                    f"i64 {value}, i64 {base}, i64 0, i1 true, i1 false)")


def bounded_decimal(value, maximum):
    # Bound the decimal text before int(): host digit limits must not escape
    # as compiler errors, and arbitrarily many leading zeroes are harmless.
    value = (value or "").lstrip("0") or "0"
    limit = str(maximum)
    if len(value) > len(limit) or (len(value) == len(limit) and value > limit):
        return None
    return int(value)


def call(e, target, node):
    if node.keywords or calls.expands_arguments(node):
        raise LLVMUnsupported("LLVM formatting requires positional arguments without expansion", node)
    source = node.args[0]
    from .json_ops import reject_class_values
    reject_class_values(source, node, target.name)
    semantic = analyzed_value_type(source)
    empty = representation.empty_literal(source)
    kind, value = ("ptr", "@" + e.string_constant(empty)) if empty is not None else e.expression(source)
    frame = calls.root_values(e, value) if kind == "ptr" else None
    if target.py_func is builtins._ascii:
        if empty is None:
            _, value = representation.render(e, semantic, kind, value, node)
        buffer = Buffer(e, node)
        result = buffer.render(lambda: e.emit_line(f"call void @pyjs.format.ascii(ptr {buffer.output}, ptr {value})"), value)
    else:
        spec_node = node.args[1] if len(node.args) > 1 else ast.Constant(value="")
        spec = spec_node.value if isinstance(spec_node, ast.Constant) else None
        specification = "@" + e.string_constant(spec) if spec is not None else e.expression(spec_node)[1]
        spec_frame = calls.root_values(e, specification)
        if empty is not None and spec == "":
            result = value
        else:
            result = format_value(e, semantic, kind, value, specification, spec, node)
        calls.pop_roots(e, spec_frame)
    calls.pop_roots(e, frame)
    return "ptr", result


def format_value(e, semantic, kind, value, specification, spec, node):
    semantic = tagged.effective_type(tagged.runtime_type(semantic), kind)
    if nullable.is_object(semantic):
        from . import erased_repr
        if spec is None:
            raise LLVMUnsupported("LLVM erased formatting requires a constant format specification", node)
        return erased_repr.call(e, semantic, kind, value, False, node, spec=spec)
    if tagged.members(semantic):
        return tagged.dispatch(e, semantic, value, "ptr",
                               lambda member, storage, payload: format_value(
                                   e, member, storage, payload, specification, spec, node))
    if nullable.member(semantic):
        if spec != "":
            raise LLVMUnsupported("LLVM optional formatting requires an empty specification", node)
        return nullable.dispatch(e, semantic, kind, value, "ptr", "@" + e.string_constant("None"),
                                 lambda member, storage, payload: format_value(e, member, storage, payload, specification, spec, node))
    method = semantic.find_attrs("__format__")
    if semantic in e.module.classes and isinstance(method, Function) and method in e.module.functions:
        if method.is_static or method.is_classmethod:
            raise LLVMUnsupported("LLVM __format__ requires an instance method", node)
        if getattr(method.return_type, "generic_name", None) != "str":
            raise LLVMUnsupported("LLVM __format__ must return str", node)
        # Bind defaults through the ordinary call machinery, but substitute the
        # already evaluated specification so a side-effecting expression runs once.
        if not method.params or getattr(method.params[0].annotation.obj, "generic_name", None) != "str":
            raise LLVMUnsupported("LLVM __format__ must accept a string specification", node)
        from .analysis import NATIVE_ENVIRONMENT
        argument = Constant(NATIVE_ENVIRONMENT.builtins.search("str"), value="")
        call_node = ast.copy_location(ast.Call(func=node.func, args=[argument], keywords=[]), node)
        with representation.method_scope(e, node):
            result = calls.bind_method(e, method, value, call_node, semantic=semantic,
                                       positional=[("ptr", specification)])[1]
        return result
    if semantic in e.module.classes and any(
            is_subclass(cls, semantic) and cls.find_attrs("__format__") is not method
            for cls in e.module.classes):
        raise LLVMUnsupported("LLVM formatting through this static base requires an explicit __format__ method", node)
    if spec is None:
        raise LLVMUnsupported("LLVM builtin values require a constant format specification", node)
    if spec == "":
        return representation.render(e, semantic, kind, value, node, representation=False)[1]
    name = enum_ops.storage_name(semantic) or semantic.generic_name
    if name not in {"str", "int", "float", "bool"}:
        e.guard_exception(node, "false", "TypeError", f"unsupported format string passed to {name}.__format__")
        return "@" + e.string_constant("")
    match = SPEC.fullmatch(spec)
    if match is None:
        if FORMAT_GRAMMAR.fullmatch(spec) is None:
            e.guard_exception(node, "false", "ValueError", "invalid format specification")
            return "@" + e.string_constant("")
        raise LLVMUnsupported("LLVM format supports alignment, sign, alternate form, width, precision and s/b/o/d/x/X/e/E/f/F/g/G/% codes", node)
    fill, explicit_alignment, alignment, sign, alternate, zero, width, precision, code = match.groups()
    alignment = explicit_alignment or alignment
    if name == "str":
        if code not in {"", "s"} or sign or alternate or alignment == "=":
            e.guard_exception(node, "false", "ValueError", "invalid string format specification")
            return "@" + e.string_constant("")
        alignment = alignment or "<"
    else:
        alignment = alignment or ("=" if zero else ">")
        if code == "s" or (code in {"b", "o", "d", "x", "X"} and (name == "float" or precision is not None)):
            e.guard_exception(node, "false", "ValueError", "invalid numeric format specification")
            return "@" + e.string_constant("")
    fill = fill or ("0" if zero else " ")
    width = bounded_decimal(width, 9223372036854775807)
    precision_limit = 9223372036854775807 if name == "str" else 2147483646
    digits = bounded_decimal(precision, precision_limit) if precision is not None else -1
    if width is None or digits is None:
        e.guard_exception(node, "false", "ValueError", "format width or precision exceeds native limits")
        return "@" + e.string_constant("")
    if name != "str":
        if code in {"e", "E", "f", "F", "g", "G", "%"}:
            if kind == "i1":
                value = e.emit_value(f"uitofp i1 {value} to double")
            elif kind == "i64":
                value = e.emit_value(f"sitofp i64 {value} to double")
            elif kind != "double":
                raise LLVMUnsupported("LLVM numeric format requires scalar numeric storage", node)
            if code == "%":
                value = e.emit_value(f"fmul double {value}, 1.0e+02")
            printf = "%" + (sign or "") + (alternate or "") + ".*" + ("f%%" if code == "%" else code)
            header = "@" + e.string_constant(printf + "\0")
            slot = e.emit_value(f"getelementptr %pyjs.string, ptr {header}, i32 0, i32 1")
            format_pointer = e.emit_value(f"load ptr, ptr {slot}")
            value = e.allocated_value(f"call ptr @pyjs.format.float({collection_ops.owner(e)}, double {value}, ptr {format_pointer}, i32 {6 if digits < 0 else digits})")
        else:
            if digits >= 0:
                if name == "float":
                    raise LLVMUnsupported("LLVM precision requires an explicit floating format code", node)
                e.guard_exception(node, "false", "ValueError", "Precision not allowed in integer format specifier")
                return "@" + e.string_constant("")
            if name == "float":
                if sign or alternate:
                    raise LLVMUnsupported("LLVM signed/alternate float formats require e/E/f/F/g/G/%", node)
                # With no precision or type code, Python pads the ordinary
                # shortest float representation, including its trailing .0.
                value = representation.render(e, semantic, kind, value, node, representation=False)[1]
            else:
                if kind == "i1":
                    value = e.emit_value(f"zext i1 {value} to i64")
                base = {"b": 2, "o": 8, "x": 16, "X": 16}.get(code, 10)
                sign_code = ord(sign) if sign in {"+", " "} else 0
                value = e.allocated_value(f"call ptr @pyjs.format.integer({collection_ops.owner(e)}, i64 {value}, i64 {base}, i64 {sign_code}, i1 {str(bool(alternate)).lower()}, i1 {str(code == 'X').lower()})")
        digits = -1
    root = calls.root_values(e, value)
    result = e.allocated_value(f"call ptr @pyjs.format.pad({collection_ops.owner(e)}, ptr {value}, ptr @{e.string_constant(fill)}, i64 {width}, i64 {digits}, i64 {ord(alignment)})")
    calls.pop_roots(e, root)
    return result
