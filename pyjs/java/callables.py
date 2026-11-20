"""Typed JVM callback interfaces and adapters for emitted functions."""

import ast

from pyjs.analysis.analyzer import callable_value_type
from pyjs.analysis.ir import Lambda
from pyjs.analysis.lambdas import lift_lambda
from pyjs.analysis.lifetime import lambda_captures
from pyjs.analysis.objects import CallableClass

from .classfile import Bytecode, ClassFile, Method
from .diagnostics import JVMUnsupported


def prepare(emitter, functions):
    for owner in functions:
        for block in owner.ir.blocks:
            for statement in getattr(block, "body", ()):
                for node in ast.walk(statement):
                    if not isinstance(node, Lambda) or node in emitter.lambdas:
                        continue
                    args = node.args
                    if args.defaults or args.kw_defaults or args.kwonlyargs or args.vararg or args.kwarg:
                        raise JVMUnsupported("JVM lambdas require fixed positional parameters without defaults", node)
                    if lambda_captures(node):
                        raise JVMUnsupported("JVM lambda captures are not implemented", node)
                    signature(emitter, node.obj, node)
                    function = lift_lambda(owner, node, f"lambda${len(emitter.lambdas)}")
                    emitter.lambdas[node] = function
                    emitter.functions.add(function)
                    functions.append(function)


def signature(emitter, value_type, node=None):
    parameters = getattr(value_type, "parameter_types", None)
    if parameters is None:
        if isinstance(value_type, CallableClass):
            raise JVMUnsupported("JVM callbacks require explicit parameter types", node)
        # Existing Android listener storage uses bare callable for Runnable.
        return "java/lang/Runnable", "run", [], "V", "()V"
    representations = value_type.parameter_representations or (None,) * len(parameters)
    if value_type.return_representation is not None or any(representations):
        raise JVMUnsupported("JVM callbacks with represented parameters or results are not implemented", node)
    if value_type.required_keywords or value_type.minimum_arguments != len(parameters):
        raise JVMUnsupported("JVM callbacks require fixed positional parameters", node)
    arguments = [emitter.value_type(parameter) for parameter in parameters]
    result = emitter.value_type(value_type.return_type)
    result = "V" if result == "N" else result
    descriptor = "(" + "".join(arguments) + ")" + result
    if descriptor == "()V":
        return "java/lang/Runnable", "run", arguments, result, descriptor
    owner = emitter.callback_interfaces.get(descriptor)
    if owner is None:
        owner = f"{emitter.main_class_name}$Callback${len(emitter.callback_interfaces)}"
        emitter.callback_interfaces[descriptor] = owner
        interface = ClassFile(owner, access=0x0601, source_file=emitter.source_file)
        interface.add_method(Method(0x0401, "call", descriptor, b"", 0, 0))
        emitter.class_files[owner] = interface
    return owner, "call", arguments, result, descriptor


def value_type(emitter, value_type):
    owner, _name, _arguments, _result, _descriptor = signature(emitter, value_type)
    return f"L{owner};"


def check_conversion(emitter, actual, expected, node):
    if actual == expected:
        return
    interfaces = {"Ljava/lang/Runnable;", *(f"L{owner};" for owner in emitter.callback_interfaces.values())}
    if actual in interfaces and expected in interfaces:
        raise JVMUnsupported("JVM callback signature adaptation is not implemented", node)


def reference(emitter, node, target):
    if (target not in emitter.functions or target.cls is not None or target.is_async
            or target.vararg or target.kwarg or target.defaults or target.kwonlyargs):
        raise JVMUnsupported("JVM function values require an emitted fixed-arity module function", node)
    interface, method, arguments, result, descriptor = signature(emitter, callable_value_type(node), node)
    if emitter.descriptor(target) != descriptor:
        raise JVMUnsupported("JVM function value has an incompatible callback signature", node)
    owner = emitter.callback_adapters.get(target)
    if owner is None:
        owner = f"{emitter.main_class_name}$Function${len(emitter.callback_adapters)}"
        emitter.callback_adapters[target] = owner
        wrapper = ClassFile(owner, source_file=emitter.source_file, interfaces=(interface,))
        wrapper.add_method(emitter.default_constructor(wrapper))
        code = Bytecode()
        slot = 1
        for argument in arguments:
            code.local({"J": 0x16, "D": 0x18, "Z": 0x15}.get(argument, 0x19), slot)
            slot += 2 if argument in {"J", "D"} else 1
        target_ref = wrapper.method_reference(
            emitter.function_owner(target), emitter.function_name(target), descriptor)
        code.emit(0xB8, target_ref.to_bytes(2, "big"))
        code.emit({"V": 0xB1, "J": 0xAD, "D": 0xAF, "Z": 0xAC}.get(result, 0xB0))
        wrapper.add_method(Method(0x0001, method, descriptor, code.render(), None, slot))
        emitter.class_files[owner] = wrapper
    emitter.code.emit(0xBB, emitter.class_file.constants.class_(owner).to_bytes(2, "big"))
    emitter.code.emit(0x59)
    constructor = emitter.class_file.method_reference(owner, "<init>", "()V")
    emitter.code.emit(0xB7, constructor.to_bytes(2, "big"))
    return f"L{interface};"


def invoke(emitter, node, value_type):
    owner, name, arguments, result, descriptor = signature(emitter, value_type, node)
    if node.keywords or len(node.args) != len(arguments):
        raise JVMUnsupported("JVM callbacks require their exact positional arguments", node)
    receiver = emitter.expression(node.func)
    if receiver != f"L{owner};":
        raise JVMUnsupported("JVM callback has an incompatible runtime type", node)
    slots = 1
    for argument, expected in zip(node.args, arguments, strict=True):
        actual = emitter.expression(argument)
        emitter.convert_native_argument(actual, expected, argument)
        slots += 2 if expected in {"J", "D"} else 1
    if slots > 255:
        raise JVMUnsupported("JVM callback exceeds the argument slot limit", node)
    reference = emitter.class_file.interface_method_reference(owner, name, descriptor)
    emitter.code.emit(0xB9, reference.to_bytes(2, "big") + bytes([slots, 0]))
    return result
