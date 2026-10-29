"""Build one adapter in a fresh directory. Invoked in a bounded subprocess."""
import argparse
import ast
import hashlib
import json
import shutil
from pathlib import Path

from perf.artifacts import code_size, javascript_ranges
from perf.harness.process import execute

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "harness"
BATCH = """
def batch(size: int, loops: int) -> str:
    checksum = 0
    for i in range(loops):
        checksum += kernel(size + i % 2)
    return str(checksum)
"""
TARGETS = ("cpython", "pyjs-js", "javascript", "pyjs-llvm", "rust", "pyjs-jvm", "java")


def build(case: str, target: str, output: Path, tools: dict) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    case_dir = ROOT / "cases" / case
    source = (case_dir / "workload.py").read_text() + "\n" + BATCH
    commands = []

    def run(command):
        commands.append([str(x) for x in command])
        result = execute(command, timeout=120, cwd=output)
        with (output / "build.log").open("a") as log:
            log.write(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    (output / "program.py").write_text(source)
    if target == "cpython":
        shutil.copyfile(ADAPTERS / "python_driver.py", output / "driver.py")
        command = [tools["python"]["path"], str(output / "driver.py")]
    elif target == "javascript":
        adapter = """
const __pyjsEntry__ = {main(size, loops) {
    let checksum = 0;
    for (let i = 0; i < loops; i++) checksum += kernel(size + i % 2);
    return String(checksum);
}};
"""
        (output / "program.cjs").write_text((case_dir / "reference.cjs").read_text() +
                                            adapter + (ADAPTERS / "node_driver.cjs").read_text())
        command = [tools["node"]["path"], str(output / "program.cjs")]
    elif target == "pyjs-js":
        from pyjs.javascript.source import compile_source
        entry = source + "\ndef main(size: int, loops: int) -> str:\n    return batch(size, loops)\n"
        # Client reachability is opt-in. Add declarations, not benchmark rewrites.
        lines = entry.splitlines()
        for node in reversed(ast.parse(entry).body):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                lines.insert(node.lineno - 1, "@js")
        entry = "from pyjs import js\n" + "\n".join(lines) + "\n"
        (output / "client.py").write_text(entry)
        with compile_source(entry, filename="workload.py", module_name="perf_workload") as result:
            javascript = result.javascript
            (output / "generated.js").write_text(javascript)
            (output / "source-ranges.json").write_text(json.dumps({
                "sha256": hashlib.sha256(javascript.encode()).hexdigest(),
                "ranges": javascript_ranges(result.source_map, (case_dir / "workload.py").read_text()),
            }))
        (output / "program.cjs").write_text(javascript + "\n" + (ADAPTERS / "node_driver.cjs").read_text())
        command = [tools["node"]["path"], str(output / "program.cjs")]
    elif target in {"java", "pyjs-jvm"}:
        if target == "pyjs-jvm":
            from pyjs.java import transpile_jvm
            compiled = transpile_jvm(
                source + "\ndef main() -> str:\n    return batch(1, 1)\n",
                filename="workload.py", class_name="PyjsProgram",
            )
            compiled.write(output)
            batch_call = "PyjsProgram.batch"
        else:
            shutil.copyfile(case_dir / "Kernel.java", output / "Kernel.java")
            code = """public final class Batch {
                public static String batch(long size, long loops) {
                    long checksum = 0;
                    for (long i = 0; i < loops; i++) checksum += Kernel.kernel(size + i % 2);
                    return Long.toString(checksum);
                }
            }"""
            (output / "Batch.java").write_text(code)
            batch_call = "Batch.batch"
        (output / "Driver.java").write_text((ADAPTERS / "Driver.java").read_text().replace("BATCH", batch_call))
        run([tools["javac"]["path"], "-cp", output, *sorted(output.glob("*.java"))])
        command = [tools["java"]["path"], "-cp", str(output), "Driver"]
        if tools["javap"]["path"]:
            disassembly = execute([tools["javap"]["path"], "-c", "-p", "-v", "-classpath", output,
                                   *[path.stem for path in sorted(output.glob("*.class"))]], timeout=30)
            (output / "bytecode.txt").write_text(disassembly.stdout + disassembly.stderr)
    elif target == "rust":
        (output / "program.rs").write_text((case_dir / "reference.rs").read_text() +
                                          "\n" + (ADAPTERS / "rust_driver.rs").read_text())
        run([tools["rustc"]["path"], "-O", "--edition=2024", output / "program.rs", "-o", output / "program"])
        command = [str(output / "program")]
    elif target == "pyjs-llvm":
        from pyjs.native.llvm import transpile_llvm_module
        module = transpile_llvm_module(source, filename="workload.py",
                                      entry_point="batch", target="library")
        (output / "generated.ll").write_text(module.llvm_ir)
        declarations, arguments = [], []
        if module.managed:
            declarations += ["extern void *pyjs_gc_new(void);", "extern void pyjs_gc_delete(void *);"]
            arguments.append("void *")
        arguments.append("int")
        if module.exceptions:
            arguments.append("void (*)(void *, void *, void *)")
        arguments += ["int64_t", "int64_t"]
        declarations.append("extern int pyjs_render_to_fd(" + ", ".join(arguments) + ");")
        values = (["heap"] if module.managed else []) + ["fileno(sink)"]
        values += ["report_error"] if module.exceptions else []
        values += ["size", "loops"]
        driver = (ADAPTERS / "native_driver.c").read_text()
        driver = driver.replace("/* DECLARATIONS */", "\n".join(declarations))
        driver = driver.replace("/* INIT */", "void *heap = pyjs_gc_new(); if (!heap) return 2;" if module.managed else "")
        driver = driver.replace("/* CLOSE */", "pyjs_gc_delete(heap);" if module.managed else "")
        driver = driver.replace("CALL", "pyjs_render_to_fd(" + ", ".join(values) + ")")
        (output / "driver.c").write_text(driver)
        run([tools["clang"]["path"], "-O2", output / "generated.ll", output / "driver.c",
             "-lm", "-o", output / "program"])
        command = [str(output / "program")]
    else:
        raise ValueError(target)
    return {"command": command, "build_commands": commands, "code_size": code_size(target, output)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case")
    parser.add_argument("target", choices=TARGETS)
    parser.add_argument("output", type=Path)
    parser.add_argument("tools", type=Path)
    args = parser.parse_args()
    result = build(args.case, args.target, args.output.resolve(), json.loads(args.tools.read_text()))
    (args.output / "build.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
