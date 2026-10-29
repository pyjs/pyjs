"""Summarize HotSpot compilation evidence from a separate diagnostic pass."""
from xml.etree import ElementTree


def summarize_jit(path):
    tree = ElementTree.parse(path)

    def relevant(method):
        return method.startswith(("PyjsProgram ", "PyjsProgram$", "Kernel ", "Kernel$", "Batch "))

    failures = []
    for task in tree.iter("task"):
        method = task.get("method", "")
        reasons = sorted({node.get("reason", "unknown") for node in task.iter("failure")})
        if relevant(method) and reasons:
            failures.append({"method": method, "compiler_level": task.get("level"),
                             "osr": task.get("compile_kind") == "osr", "reasons": reasons})
    compiled = sorted({(node.get("method", ""), node.get("compiler", ""))
                       for node in tree.iter("nmethod") if relevant(node.get("method", ""))})
    return {"status": "ok", "failures": failures,
            "compiled": [{"method": method, "compiler": compiler} for method, compiler in compiled]}
