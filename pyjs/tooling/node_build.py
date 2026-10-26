"""Compile Python entry points to self-contained Node/CommonJS bundles."""

import importlib
from collections.abc import Callable
from pathlib import Path

from pyjs.javascript.transpiler import bundle_with_source_map, javascript_identifier


def resolve_entry(target: str) -> Callable:
    module, separator, name = target.partition(":")
    return getattr(importlib.import_module(module), name if separator else "main")


def build_node(entry: Callable, output: Path, *, export_name: str = "main",
               executable: bool = True) -> Path:
    """Emit a CommonJS entry and Python source map without executing the entry."""
    if not export_name.isidentifier():
        raise ValueError("Node export name must be an identifier")
    output = output.resolve()
    if output.suffix != ".cjs":
        raise ValueError("Node bundle output must end in .cjs")
    generated, _ = bundle_with_source_map(
        entry, include_main=True, include_css=False, call_main=False,
        expose_entry=True, filename=output.name,
    )
    if generated.npm_imports:
        raise ValueError("Node bundles do not yet support managed browser npm imports")
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = f"\nmodule.exports = {{{export_name}: __pyjsEntry__.{javascript_identifier(entry.__name__)}}};\n"
    if executable:
        suffix += (
            "if (require.main === module) {\n"
            "  let settled = false;\n"
            "  process.on('exit', () => {\n"
            "    if (!settled) {\n"
            "      console.error('Node entry did not complete'); process.exitCode = 1;\n"
            "    }\n"
            "  });\n"
            f"  Promise.resolve().then(() => module.exports.{export_name}()).then(() => {{\n"
            "    settled = true;\n"
            "  }, error => {\n"
            "    settled = true; console.error(error); process.exitCode = 1;\n"
            "  });\n}\n"
        )
    prefix = "#!/usr/bin/env node\n" if executable else ""
    output.write_text(prefix + generated.javascript + suffix +
                      f"//# sourceMappingURL={output.name}.map\n", encoding="utf-8")
    output.with_suffix(output.suffix + ".map").write_text(
        generated.source_map.shifted(1 if executable else 0).to_json(), encoding="utf-8",
    )
    if executable:
        output.chmod(output.stat().st_mode | 0o111)
    return output
