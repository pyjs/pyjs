"""PyJS DOM UI for a JSON snapshot; rendered on request, never written as a site."""
from perf.categories import (
    CATEGORIES,
    METRICS,
    category_for,
    heat_style,
    ratio_label,
    summarize_category,
)
from pyjs.web.domx import tag

LABELS = {"cpython": "CPython", "javascript": "JavaScript", "pyjs-js": "Py → JS",
          "rust": "Rust", "pyjs-llvm": "Py → LLVM", "java": "Java", "pyjs-jvm": "Py → JVM"}
GROUPS = {"js": ("JavaScript", "javascript", "pyjs-js"),
          "native": ("Native", "rust", "pyjs-llvm"), "jvm": ("JVM", "java", "pyjs-jvm")}


def column_attributes(target):
    return {"data-target": target,
            "class": "pyjs" if target.startswith("pyjs-") else "group-start"}


def select(name, title, options, selected=""):
    return tag("label", title, tag("select", {"id": name}, *[
        tag("option", {"value": value, **({"selected": ""} if value == selected else {})}, label)
        for value, label in options]))


def view(data, runs, selected, prefix):
    tables, sources, cases = {}, [], {}
    groups = {}
    latest = selected == runs[0]
    for row in data["rows"]:
        case, target, size = row["case"], row["target"], row["size"]
        cases[case] = row["metadata"]
        groups.setdefault((case, size), {})[target] = row
    for (case, size), results in sorted(groups.items(), key=lambda item: (cases[item[0][0]]["name"], item[0][1])):
        table = tables.setdefault(category_for(case), [])
        cells = [result_cell(results.get(target), case, size, target) for target in LABELS]
        table.append(tag("tr", {"id": f"comparison-{case}-{size}", "data-case": case, "data-size": str(size)},
                         tag("th", {"scope": "row"}, tag("button", {"type": "button", "class": "row-source",
                             "data-source-button": "", "aria-expanded": "false", "aria-controls": f"source-panel-{case}-{size}"}, cases[case]["name"]),
                             tag("span", {"class": "input-size"}, f"N = {size:,}")), *cells))
        table.append(source_panel(data, case, size, cases[case]))
    for case in cases:
        for target, filename in (("cpython", "workload.py"), ("javascript", "reference.cjs"),
                                 ("rust", "reference.rs"), ("java", "Kernel.java")):
            sources.append(tag("pre", {"id": f"source-{case}-{target}"},
                data["sources"].get(f"cases/{case}/{filename}", "Source not recorded in this snapshot.")))
        for target, filename in (("pyjs-js", "generated.js"), ("pyjs-llvm", "generated.ll"), ("pyjs-jvm", "bytecode.txt")):
            artifact = f"build/{case}/{target}/{filename}"
            available = any(artifact in row.get("artifacts", {}) for row in data["rows"] if row["case"] == case)
            sources.append(tag("pre", {"id": f"source-{case}-{target}",
                "data-url": f"{prefix}artifact/{selected}/{artifact}" if available else ""},
                "Generated code was not recorded for this configuration."))
    return tag("main",
        tag("header", tag("p", {"class": "eyebrow"}, "PyJS / Performance lab"),
            tag("h1", "Performance comparison"),
            tag("p", {"class": "lead"}, "Compare the same workload across runtimes. Shared Python kernels, with handwritten JavaScript, Rust and Java references.")),
        tag("p", {"class": "run-status", "data-latest": str(latest).lower()},
            tag("strong", "Latest run" if latest else "Older saved run"),
            f" · {data['label']} · {data['created']}",
            *([] if latest else [tag("a", {"href": prefix}, "View latest run →")])),
        tag("div", {"class": "toolbar"},
            select("metric", "Metric", [("warm", "Warmed time / iteration"), ("startup", "Fresh process + one iteration"),
                                          ("memory", "Peak process RSS"), ("compile", "Build time")])),
        tag("p", {"class": "meta", "id": "comparison-help"}, "Every target compares with CPython. Handwritten and transpiled implementations sit side by side. Lower is better. — means no valid comparison."),
        tag("p", {"class": "meta"}, "Code size counts the complete runnable benchmark, including scaffolding and its measurement driver, but not installed runtimes. Gzip is shown for JavaScript; it does not change the code."),
        tag("p", {"class": "heat-legend"}, tag("span", {"class": "heat-key", "aria-hidden": "true"}),
            "Best → worst among non-CPython targets (log scale). CPython stays neutral; all ratios still compare with it."),
        category_overview(data),
        tag("p", {"class": "source-help"}, "In the workload tables, click any runtime cell to compare code ↓",
            tag("span", " The outlined cell matches the outlined code pane. Click another cell to switch.")),
        *[tag("section", {"id": "category-" + key, "class": "workload-category", "aria-labelledby": "heading-" + key},
              tag("h2", {"id": "heading-" + key}, label), tag("p", {"class": "meta"}, description),
              tag("a", {"class": "back-overview", "href": "#category-overview"}, "↑ Category overview"),
              comparison_table(tables[key], label))
          for key, (label, description, _) in CATEGORIES.items() if key in tables],
        tag("p", {"class": "meta scroll-hint"}, "Scroll the page horizontally to compare all runtimes. Workload names stay pinned."),
        tag("div", {"hidden": "", "class": "source-library"}, *sources),
        tag("footer",
            tag("p", {"class": "meta"}, f"Measured on {data['cpu']} · {data['platform']}"),
            tag("p", {"class": "meta"}, " · ".join(
                data["tools"][name]["version"].splitlines()[0]
                for name in ("python", "node", "rustc", "java", "clang")
                if data["tools"].get(name, {}).get("version"))),
            tag("p", "These results are machine-specific. ",
                tag("a", {"href": "https://github.com/pyjs/pyjs/tree/main/perf"}, "Run the performance harness"),
                " to compare on your own hardware."),
            tag("div", {**({"hidden": ""} if len(runs) == 1 else {})},
                select("snapshot", "Saved runs", [("", "Latest run (default)")] + [(name, name) for name in runs[1:]],
                       "" if latest else selected))))


def comparison_table(rows, label):
    return tag("div", {"class": "table-wrap"},
        tag("table", {"class": "comparison-table", "aria-describedby": "comparison-help"},
            tag("caption", {"class": "sr-only"}, label + " workloads by runtime"),
            tag("thead", tag("tr", {"class": "group-headings"},
                tag("th", {"scope": "col", "rowspan": "2", "class": "workload-heading"}, "Workload / input"),
                tag("th", {"scope": "col", "rowspan": "2", **column_attributes("cpython")}, "CPython"),
                *[tag("th", {"scope": "colgroup", "colspan": "2", "data-group": key}, label)
                  for key, (label, _, _) in GROUPS.items()]),
                tag("tr", {"class": "target-headings"}, *[
                    tag("th", {"scope": "col", **column_attributes(target)}, label)
                    for target, label in LABELS.items() if target != "cpython"])), tag("tbody", *rows)))


def category_overview(data):
    rows = []
    for key, (label, _, _) in CATEGORIES.items():
        selected = [row for row in data["rows"] if category_for(row["case"]) == key]
        if not selected:
            continue
        scores = {metric: summarize_category(selected, LABELS, metric) for metric in METRICS}
        colors = {metric: [value for target, value in scores[metric].items()
                           if target != "cpython" and value is not None] for metric in METRICS}
        cells = []
        for target in LABELS:
            attributes = {"data-summary-target": target}
            for metric in METRICS:
                score = scores[metric][target]
                attributes["data-label-" + metric] = "Baseline" if target == "cpython" and score is not None else ratio_label(score, metric)
                attributes["data-style-" + metric] = "" if target == "cpython" else heat_style(score, colors[metric])
            attributes["style"] = attributes["data-style-warm"]
            cells.append(tag("td", attributes, tag("a", {"href": "#category-" + key},
                tag("strong", {"class": "category-value"}, attributes["data-label-warm"]))))
        rows.append(tag("tr", {"data-category": key}, tag("th", {"scope": "row"}, tag("a", {"href": "#category-" + key}, label + " ↓")), *cells))
    return tag("section", {"id": "category-overview", "aria-labelledby": "category-title"},
        tag("h2", {"id": "category-title"}, "Performance by workload type"),
        tag("p", {"class": "meta"}, "Click a category row to jump to its workloads. Every section stays on the page. Values compare with CPython for the selected metric."),
        tag("details", tag("summary", "How category averages work"), tag("div",
            tag("p", "Geometric mean of target/CPython ratios: input sizes are averaged within each workload, then workloads receive equal weight."),
            tag("p", "Colors compare category averages across non-CPython targets, not averages of colors. Categories describe primary behavior, not measured CPU or memory bottlenecks. These exploratory workloads are not a general language ranking."))),
        tag("div", {"class": "table-wrap"}, tag("table", {"class": "category-table"},
            tag("caption", {"class": "sr-only"}, "Category averages relative to CPython"),
            tag("thead", tag("tr", tag("th", {"scope": "col"}, "Category"),
                *[tag("th", {"scope": "col"}, label) for label in LABELS.values()])), tag("tbody", *rows))))


def source_panel(data, case, size, metadata):
    return tag("tr", {"id": f"source-panel-{case}-{size}", "class": "source-row", "data-source-case": case, "hidden": ""},
        tag("td", {"colspan": str(len(LABELS) + 1), "class": "source-cell"},
            tag("section", {"class": "source-panel", "aria-label": f"Source comparison for {metadata['name']}, N = {size}"},
                tag("div", {"class": "source-toolbar"}, tag("strong", f"{metadata['name']} · N = {size:,}"),
                    tag("button", {"type": "button", "data-close-source": ""}, "Close source")),
                tag("details", {"class": "source-notes"}, tag("summary", "Workload and comparison notes"),
                    tag("div", tag("p", metadata["description"]), tag("p", metadata["notes"]))),
                tag("div", {"class": "source-split"},
                    tag("section", tag("h3", "Python · shared source"),
                        tag("pre", {"class": "python-code", "tabindex": "0", "aria-label": "Python source; scroll to read"},
                            data["sources"].get(f"cases/{case}/workload.py", "Source not recorded in this snapshot."))),
                    tag("section", {"class": "selected-source"}, tag("p", {"class": "source-selection-label"}, "Selected cell ↓"),
                        tag("div", {"class": "target-source-heading"}, tag("h3", {"class": "target-title"}, "Selected runtime"),
                        tag("a", {"class": "source-download", "hidden": "", "target": "_blank", "rel": "noopener"}, "Open full artifact")),
                        tag("p", {"class": "source-status", "role": "status"}, ""),
                        tag("div", {"class": "target-code", "tabindex": "0", "aria-label": "Selected runtime source; scroll to read or expand folded support code"}, ""))))))


def result_cell(row, case, size, target):
    attributes = column_attributes(target)
    values = {}
    key = case + "-" + target + "-" + str(size)
    if row is not None:
        ok = row["status"] == "ok"
        values = {"warm": row.get("warm_seconds", {}).get("median"),
                  "startup": row.get("startup", {}).get("median"),
                  "memory": row.get("peak_rss_kib"), "compile": row.get("build_seconds")}
        # A failed measurement must never appear to beat a validated result.
        values = {key: value for key, value in values.items() if ok}
    attributes.update({"data-" + metric: str(values[metric]) if values.get(metric) is not None else ""
                       for metric in ("warm", "startup", "memory", "compile")})
    comparisons = [] if target == "cpython" else [
        tag("span", {"class": "ratio", "data-reference": "cpython"},
            tag("span", {"class": "ratio-value"}, "—"))]
    size_info = (row or {}).get("code_size")
    code_label = "Code —"
    if size_info:
        code_label = f"Code {size_info['bytes'] / 1024:.1f} KiB"
        if "gzip_bytes" in size_info:
            code_label += f" · gzip {size_info['gzip_bytes'] / 1024:.1f} KiB"
    return tag("td", attributes, tag("button", {"type": "button", "class": "measurement", "data-source-button": "",
        "data-source-label": LABELS[target] + (" · generated code" if target.startswith("pyjs-") else " · source"),
        "aria-describedby": "source-action-" + key,
        "aria-expanded": "false", "aria-controls": f"source-panel-{case}-{size}"}, "—"),
        tag("span", {"class": "source-cue", "id": "source-action-" + key}, "View code ↓"), *comparisons,
        tag("span", {"class": "code-size"}, code_label))
