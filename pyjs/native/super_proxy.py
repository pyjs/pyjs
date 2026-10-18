"""LLVM protocol dependencies for lexical super lookup."""

import ast

from pyjs.analysis import super_proxy
from pyjs.analysis.super_proxy import is_receiver as is_receiver
from pyjs.analysis.type_relations import is_builtin_class

from .errors import LLVMUnsupported


def prepare(function):
    for node in super_proxy.prepare(function, LLVMUnsupported, "LLVM"):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and is_receiver(node.func.value) and node.func.attr == "__str__"
                and is_builtin_class(getattr(node.func.obj, "cls", None), "object")):
            # object.__str__ bypasses the subclass's str override but still
            # invokes its repr. An ordered str/repr fallback stops too soon.
            node.runtime_protocols = (*node.runtime_protocols, (function.cls, ("__repr__",)))
