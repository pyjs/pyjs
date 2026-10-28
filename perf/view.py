"""PyJS DOM UI for a JSON snapshot; rendered on request, never written as a site."""
import json
import statistics

from pyjs.web.domx import tag

LABELS = {"cpython": "CPython", "javascript": "JavaScript", "pyjs-js": "Py → JS",
          "rust": "Rust", "pyjs-llvm": "Py → LLVM", "java": "Java", "pyjs-jvm": "Py → JVM"}
GROUPS = {"js": ("JavaScript", "javascript", "pyjs-js"),
          "native": ("Native", "rust", "pyjs-llvm"), "jvm": ("JVM", "java", "pyjs-jvm")}
TARGET_GROUP = {target: group for group, (_, reference, compiled) in GROUPS.items()
                for target in (reference, compiled)}


def column_attributes(target):
    return {"data-target": target, "data-group": TARGET_GROUP.get(target, "python"),
            "class": "pyjs" if target.startswith("pyjs-") else "group-start"}


def select(name, title, options, selected=""):
    return tag("label", title, tag("select", {"id": name}, *[
        tag("option", {"value": value, **({"selected": ""} if value == selected else {})}, label)
        for value, label in options]))


def view(data, runs, selected, prefix):
    table, sources, diagnostics, cases = [], [], [], {}
    groups = {}
    revision = data["revision"][:12] + (" (uncommitted changes)" if data["dirty"] else "")
    for row in data["rows"]:
        case, target, size = row["case"], row["target"], row["size"]
        cases[case] = row["metadata"]
        groups.setdefault((case, size), {})[target] = row
        key = case + "-" + target + "-" + str(size)
        diagnostics.append(tag("details", {"id": key}, tag("summary", f"{case} / {target} / {size}"),
                               evidence(row, selected, prefix)))
    for (case, size), results in groups.items():
        cells = [result_cell(results.get(target), case, size, target) for target in LABELS]
        table.append(tag("tr", {"data-case": case, "data-size": str(size)},
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
                "Generated code was not recorded for this configuration. See its measurement evidence."))
    return tag("main",
        tag("header", tag("p", {"class": "eyebrow"}, "PyJS / Performance lab"),
            tag("h1", "Performance comparison"),
            tag("p", {"class": "lead"}, "Compare the same workload across runtimes. Shared Python kernels, with handwritten JavaScript, Rust and Java references.")),
        tag("div", {"class": "toolbar"}, select("snapshot", "Snapshot", [(name, name) for name in runs], selected),
            select("metric", "Metric", [("warm", "Warmed time / iteration"), ("startup", "Fresh process + one iteration"),
                                          ("memory", "Peak process RSS"), ("compile", "Build time")]),
            select("group", "Show targets", [("all", "All targets"),
                *[(key, "CPython + " + label) for key, (label, _, _) in GROUPS.items()]]),
            select("workload", "Workload", [("all", "All workloads"), *[(case, m["name"]) for case, m in cases.items()]])),
        tag("aside", {"class": "notice"}, "Exploratory measurements, not a language ranking. Warnings and failures link to their evidence." +
            (" Snapshot interrupted: coverage is incomplete." if not data["complete"] else "")),
        tag("p", {"class": "meta", "id": "comparison-help"}, "Every target compares with CPython. Handwritten and transpiled implementations sit side by side. Lower is better. — means no valid comparison."),
        tag("p", {"class": "heat-legend"}, tag("span", {"class": "heat-key", "aria-hidden": "true"}),
            "Best → worst in each row (log scale, visible targets). Missing/zero values stay neutral. Click a runtime cell to compare source."),
        tag("div", {"class": "table-scroll", "tabindex": "0", "role": "region", "aria-label": "Runtime comparison; scroll to see all columns"},
            tag("table", {"class": "comparison-table", "data-view": "all", "aria-describedby": "comparison-help"},
                tag("caption", {"class": "sr-only"}, "Workloads by runtime"),
                tag("thead",
                    tag("tr", {"class": "group-headings"},
                        tag("th", {"scope": "col", "rowspan": "2", "class": "workload-heading"}, "Workload / input"),
                        tag("th", {"scope": "col", "rowspan": "2", **column_attributes("cpython")}, "CPython"),
                        *[tag("th", {"scope": "colgroup", "colspan": "2", "data-group": key}, label)
                          for key, (label, _, _) in GROUPS.items()]),
                    tag("tr", {"class": "target-headings"}, *[
                        tag("th", {"scope": "col", **column_attributes(target)}, label)
                        for target, label in LABELS.items() if target != "cpython"])), tag("tbody", *table))),
        tag("p", {"class": "meta scroll-hint"}, "Scroll horizontally to compare all runtimes. Workload names stay pinned."),
        tag("details", tag("summary", "Run information, versions and JSON"), tag("div",
            tag("p", {"class": "meta"}, f"{data['label']} · {data['created']}\n{data['cpu']} · {data['platform']}\nRevision {revision}"),
            tag("p", " ".join(data["warnings"])),
            tag("pre", json.dumps({"tools": data["tools"], "policy": data["policy"], "source_sha256": data["source_sha256"]}, indent=2)),
            tag("a", {"href": f"{prefix}results/{selected}.json"}, "Download JSON snapshot"))),
        tag("details", tag("summary", "Measurement contract"), tag("div",
            tag("p", "Correctness is checked before timing and on every batch. Warmed values are medians of process medians; inspect warmup traces and warnings. Allocation and checksum work remain included."),
            tag("p", "LLVM includes arena lifecycle and a checksum file write per batch; other adapters return a string. RSS includes the VM baseline. Startup includes process launch and teardown, not compilation."))),
        tag("div", {"hidden": "", "class": "source-library"}, *sources),
        tag("h2", "Measurement evidence"), *diagnostics,
        tag("footer", "Python UI rendered by PyJS. JSON snapshots are the data, not generated HTML reports."))


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
                    tag("section", tag("div", {"class": "target-source-heading"}, tag("h3", {"class": "target-title"}, "Selected runtime"),
                        tag("a", {"class": "source-download", "hidden": "", "target": "_blank", "rel": "noopener"}, "Open full artifact")),
                        tag("p", {"class": "source-status", "role": "status"}, ""),
                        tag("pre", {"class": "target-code", "tabindex": "0", "aria-label": "Selected runtime source; scroll to read"}, ""))))))


def evidence(row, selected, prefix):
    panels = [tag("p", {"class": "warning"}, warning) for warning in row.get("warnings", [])]
    traces = []
    for index, fork in enumerate(row.get("forks", []), 1):
        warmups = [s["ns"] / row["loops"] / 1e6 for s in fork if s["phase"] == "warmup"]
        samples = [s["ns"] / row["loops"] / 1e6 for s in fork if s["phase"] == "sample"]
        if samples:
            values = [str(index), f"{warmups[0]:.3f}" if warmups else "—",
                      f"{warmups[-1]:.3f}" if warmups else "—",
                      f"{statistics.median(samples):.3f}", f"{min(samples):.3f}–{max(samples):.3f}"]
            traces.append(tag("tr", *[tag("td", value) for value in values]))
    if traces:
        panels.extend([tag("p", f"Milliseconds per kernel call; {row['loops']} calls per batch. Warmup endpoints are context, not a convergence guarantee."),
                       tag("div", {"class": "trace-scroll", "tabindex": "0", "role": "region",
                                   "aria-label": "Per-fork timings; scroll to see all columns"}, tag("table", {"class": "trace-table"},
                           tag("thead", tag("tr", *[tag("th", title) for title in
                               ("Fork", "First warmup", "Last warmup", "Sample median", "Sample range")])),
                           tag("tbody", *traces)))])
    jit = row.get("jvm_diagnostics")
    if jit:
        panels.append(tag("h3", "JVM compilation · separate diagnostic pass"))
        if jit["status"] != "ok":
            panels.append(tag("p", jit.get("error", "Unavailable")))
        else:
            failures = jit.get("failures", [])
            panels.append(tag("p", "Compilation failures recorded:" if failures else
                              "No compilation failure recorded. This alone does not prove every method compiled or reached steady state."))
            panels.extend(tag("p", {"class": "warning"}, item["method"] + ": " + "; ".join(item["reasons"])) for item in failures)
            panels.append(tag("details", tag("summary", "Successfully compiled benchmark methods"),
                              tag("div", tag("pre", json.dumps(jit.get("compiled", []), indent=2)))))
        panels.extend(tag("p", tag("a", {"href": f"{prefix}artifact/{selected}/{path}"}, path.rsplit("/", 1)[-1]))
                      for path in row.get("artifacts", {})
                      if path.rsplit("/", 1)[-1] in {f"{row['size']}-jit.xml", f"{row['size']}-jit.log"})
    panels.append(tag("details", tag("summary", "Raw samples, commands and metadata"),
                      tag("div", tag("pre", json.dumps({k: v for k, v in row.items() if k != "metadata"}, indent=2)))))
    return tag("div", *panels)


def result_cell(row, case, size, target):
    attributes = column_attributes(target)
    values = {}
    status = "not run"
    key = case + "-" + target + "-" + str(size)
    if row is not None:
        ok = row["status"] == "ok"
        values = {"warm": row.get("warm_seconds", {}).get("median"),
                  "startup": row.get("startup", {}).get("median"),
                  "memory": row.get("peak_rss_kib"), "compile": row.get("build_seconds")}
        # A failed measurement must never appear to beat a validated result.
        values = {key: value for key, value in values.items() if ok}
        status = ("warnings" if row.get("warnings") else "details") if ok else row["status"]
    attributes.update({"data-" + metric: str(values[metric]) if values.get(metric) is not None else ""
                       for metric in ("warm", "startup", "memory", "compile")})
    evidence = tag("a", {"href": "#" + key, "class": "evidence" + (" warning" if status not in {"details", "not run"} else "")}, status) if row is not None else tag("span", {"class": "evidence"}, status)
    comparisons = []
    if target == "cpython":
        comparisons.append(tag("span", {"class": "baseline-note"}, "Python baseline"))
    else:
        comparisons.append(tag("span", {"class": "ratio", "data-reference": "cpython"},
            tag("span", {"class": "ratio-value"}, "—"), tag("small", "vs CPython")))
    return tag("td", attributes, tag("button", {"type": "button", "class": "measurement", "data-source-button": "",
        "data-source-label": LABELS[target] + (" · generated code" if target.startswith("pyjs-") else " · source"),
        "aria-label": f"Show {LABELS[target]} source for {case}, N = {size}",
        "aria-expanded": "false", "aria-controls": f"source-panel-{case}-{size}"}, "—"), *comparisons, evidence)
