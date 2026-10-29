"""Descriptive workload groups and equal-workload relative summaries."""
import math
import statistics

CATEGORIES = {
    "numeric": ("Numeric computation", "Arithmetic-heavy loops and numerical kernels.",
                ("matrix", "mandelbrot", "spectralnorm", "nbody")),
    "collections": ("Arrays & maps", "Indexed access, sorting, sieving and dictionary updates.",
                    ("sieve", "heapsort", "histogram")),
    "objects": ("Allocation & objects", "Object creation, tree traversal and mutable object state.",
                ("objects", "binarytrees", "bounce")),
    "recursion": ("Recursion & search", "Calls, backtracking and recursive state changes.",
                  ("fibonacci", "queens", "permute", "towers")),
    "text": ("Text processing", "Character scanning and string operations.", ("textscan",)),
    "other": ("Other workloads", "Workloads not yet assigned a primary category.", ()),
}
METRICS = ("warm", "startup", "memory", "compile", "size")


def category_for(case):
    return next((key for key, (_, _, cases) in CATEGORIES.items() if case in cases), "other")


def measurement(row, metric):
    if not row or row["status"] != "ok":
        return None
    value = {"warm": row.get("warm_seconds", {}).get("median"),
             "startup": row.get("startup", {}).get("median"),
             "memory": row.get("peak_rss_kib"), "compile": row.get("build_seconds"),
             "size": (row.get("code_size") or {}).get("bytes")}[metric]
    return value if isinstance(value, (float, int)) and math.isfinite(value) and value > 0 else None


def summarize_category(rows, targets, metric):
    """Target / CPython; average log ratios over sizes, then over workloads."""
    inputs = {}
    for row in rows:
        inputs.setdefault((row["case"], row["size"]), {})[row["target"]] = row
    scores = {}
    for target in targets:
        cases = {}
        scores[target] = None
        for (case, _), results in inputs.items():
            baseline = measurement(results.get("cpython"), metric)
            value = measurement(results.get(target), metric)
            if baseline is None or value is None:
                break
            cases.setdefault(case, []).append(math.log(value) - math.log(baseline))
        else:
            if cases:
                scores[target] = math.exp(statistics.mean(statistics.mean(values) for values in cases.values()))
    return scores


def ratio_label(ratio, metric):
    if ratio is None:
        return "—"
    factor = round(1 / ratio if ratio < 1 else ratio, 2)
    if factor == 1:
        return "≈ same"
    suffix = ("less memory" if ratio < 1 else "more memory") if metric == "memory" else ("faster" if ratio < 1 else "slower")
    if metric == "size":
        suffix = "smaller" if ratio < 1 else "larger"
    return f"{factor}× {suffix}"


def heat_style(value, values):
    if value is None or not values or min(values) == max(values):
        return ""
    heat = (math.log(value) - math.log(min(values))) / (math.log(max(values)) - math.log(min(values)))
    return f"background-color:hsl({round(155 - 135 * heat, 2)} 32% 18%)"
