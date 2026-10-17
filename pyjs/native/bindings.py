"""Physical local declarations shared by native feature discovery and emission."""

import ast

from pyjs.analysis.objects import Instance, LocalScope


def local_storage_binding(function, target):
    """Resolve one slot's declaration, independently of a read's flow type."""
    name = target.id if isinstance(target, ast.Name) else target.arg if isinstance(target, ast.arg) else target.name
    binding = getattr(target, "obj", None)
    if isinstance(target, ast.arg) and isinstance(binding, Instance):
        # Lowered loop targets retain their own binding. A later loop can reuse
        # the name for an unrelated tuple layout; the final scope is not this
        # write's contract. An authored declaration still wins through the
        # binding's storage_declaration link.
        return binding.storage_declaration
    scope = getattr(binding, "scope", function.scope)
    # Flow scopes own declarations and merged branch bindings too. Resolve
    # their common declaration instead of using a branch's concrete value.
    while isinstance(scope, LocalScope):
        binding = scope.names.get(name, binding)
        if scope is function.scope:
            break
        scope = scope.parent
    return binding.storage_declaration if isinstance(binding, Instance) else binding
