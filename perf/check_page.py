"""Exercise the live PyJS UI with an owned managed Chrome."""
import argparse
import asyncio
import json
import math
from pathlib import Path

from perf.view import GROUPS, LABELS
from pyjs.tooling.browser import Browser


async def check_comparison_edges(page):
    """Exercise missing/zero measurements and the fixed baseline, then restore data."""
    original = await page.evaluate("""Array.from(document.querySelector('tbody tr[data-case]').querySelectorAll('td[data-target]'))
      .map(cell => [cell.dataset.target, cell.getAttribute('data-warm')])""")
    try:
        for python, handwritten, compiled, expected in (
            ("100", "20", "25", ["5.0× faster", "4.0× faster"]),
            ("100", "100", "200", ["same", "2.0× slower"]),
            ("100", "", "25", ["—", "4.0× faster"]),
            ("", "20", "25", ["—", "—"]),
            ("0", "20", "25", ["—", "—"]),
            ("100", "0", "25", ["—", "4.0× faster"]),
            ("100", "20", "", ["5.0× faster", "—"]),
            ("100", "100.01", "99.99", ["≈ same", "≈ same"]),
        ):
            values = [["cpython", python], ["javascript", handwritten], ["pyjs-js", compiled]]
            result = await page.evaluate("""(() => {
              const row = document.querySelector('tbody tr[data-case]');
              for (const [target, value] of VALUES)
                row.querySelector('td[data-target="' + target + '"]').setAttribute('data-warm', value);
              document.querySelector('#metric').dispatchEvent(new Event('change'));
              return Array.from(row.querySelectorAll('td[data-target=javascript] .ratio-value, td[data-target=pyjs-js] .ratio-value'))
                .map(item => item.textContent);
            })()""".replace("VALUES", json.dumps(values)))
            assert result == expected, (values, result)
    finally:
        await page.evaluate("""(() => {
          const row = document.querySelector('tbody tr[data-case]');
          for (const [target, value] of VALUES)
            row.querySelector('td[data-target="' + target + '"]').setAttribute('data-warm', value);
          document.querySelector('#metric').dispatchEvent(new Event('change'));
        })()""".replace("VALUES", json.dumps(original)))


async def check_heatmap(page):
    """Validate magnitudes, neutral edge cases and scaling to visible targets."""
    original = await page.evaluate("""Array.from(document.querySelector('tbody tr[data-case]').querySelectorAll('td[data-target]'))
      .map(cell => [cell.dataset.target, cell.getAttribute('data-warm')])""")
    try:
        for values in ([100, 10, 1], [1000000, 10, 1], [0.001, 10, 1],
                       [100, 100, 100], [0, None, 1], [10, 20, 40]):
            heats = await page.evaluate("""(() => {
              const group = document.querySelector('#group'); group.value = 'js';
              const cells = document.querySelector('tbody tr[data-case]').querySelectorAll('td[data-target]');
              VALUES.forEach((value, i) => cells[i].setAttribute('data-warm', value ?? ''));
              group.dispatchEvent(new Event('change'));
              return Array.from(cells).map(cell => cell.getAttribute('data-heat'));
            })()""".replace("VALUES", json.dumps(values)))
            positive = [value for value in values[1:] if value and value > 0]
            assert heats[0] is None, "CPython must not participate in the color scale"
            for value, heat in zip(values[1:], heats[1:3], strict=True):
                if not value or min(positive) == max(positive):
                    assert heat is None, (values, heats)
                else:
                    expected = math.log(value / min(positive)) / math.log(max(positive) / min(positive))
                    assert abs(float(heat) - expected) < 1e-9, (values, heats)
            assert heats[3:] == [None] * 4, "hidden targets must not retain colors"
    finally:
        await page.evaluate("""(() => {
          const row = document.querySelector('tbody tr[data-case]');
          for (const [target, value] of VALUES)
            row.querySelector('td[data-target="' + target + '"]').setAttribute('data-warm', value ?? '');
          const group = document.querySelector('#group'); group.value = 'all';
          group.dispatchEvent(new Event('change'));
        })()""".replace("VALUES", json.dumps(original)))


async def check_sources(page, output):
    cell = 'tbody tr[data-case]:first-child td[data-target="javascript"]'
    panel = '.source-row:not([hidden])'
    header = 'tbody tr[data-case]:first-child .row-source'
    python = 'tbody tr[data-case]:first-child td[data-target="cpython"] button'
    # Header and CPython share a runtime, but only the same cell toggles closed.
    await page.click(header)
    await page.click(python)
    assert await page.evaluate("document.querySelectorAll('.source-row:not([hidden])').length") == 1
    assert await page.evaluate("document.querySelector('[data-source-selected]').dataset.target") == 'cpython'
    await page.click(header)
    assert await page.evaluate("document.querySelector('[data-source-selected]').tagName") == 'TH'
    await page.click(header)
    assert await page.evaluate("document.querySelectorAll('.source-row:not([hidden])').length") == 0
    await page.click(cell + ' button')
    assert await page.evaluate("document.querySelectorAll('.source-row:not([hidden])').length") == 1
    assert await page.evaluate("document.querySelector('[data-source-selected]').dataset.target") == "javascript"
    assert await page.evaluate("""getComputedStyle(document.querySelector('[data-source-selected]')).outlineColor ===
      getComputedStyle(document.querySelector('.source-row:not([hidden]) .selected-source')).outlineColor""")
    assert await page.evaluate("""(() => {
      const panel = document.querySelector('.source-row:not([hidden])');
      const row = panel.previousElementSibling;
      return row.dataset.case === panel.dataset.sourceCase &&
        panel.querySelector('.python-code').textContent === document.getElementById('source-' + row.dataset.case + '-cpython').textContent &&
        panel.querySelector('.target-code').textContent === document.getElementById('source-' + row.dataset.case + '-javascript').textContent;
    })()""")
    await page.evaluate("document.querySelector('.source-row:not([hidden])').scrollIntoView({block:'center'})")
    await page.screenshot(output / "source-desktop.png")
    # Switching cells updates the right pane, not the left one or the row.
    await page.click('tbody tr[data-case]:first-child td[data-target="cpython"] button')
    assert await page.evaluate(f"document.querySelector('{panel} .target-code').textContent === document.querySelector('{panel} .python-code').textContent")
    await page.click('tbody tr[data-case]:first-child td[data-target="pyjs-js"] button')
    await page.wait_for(f"document.querySelector('{panel} .source-status').textContent === ''", "generated source")
    assert await page.evaluate(f"document.querySelector('{panel} .target-code').textContent.length > 0")
    assert await page.evaluate(f"!document.querySelector('{panel} .source-download').hidden")
    await page.evaluate("document.querySelector('.source-row:not([hidden])').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
    assert await page.evaluate("document.querySelectorAll('.source-row:not([hidden])').length") == 0
    assert await page.evaluate("document.querySelectorAll('[data-source-selected]').length") == 0
    assert await page.evaluate("document.activeElement.closest('td').dataset.target") == "pyjs-js"
    # Stale requests, failed requests and source HTML must not mutate the page.
    await page.evaluate("""window.savedSourceFetch = window.fetch;
      window.fetch = () => new Promise(resolve => { window.finishSourceFetch = resolve; });""")
    try:
        await page.click('tbody tr[data-case]:first-child td[data-target="pyjs-js"] button')
        await page.click(cell + ' button')
        await page.evaluate("window.finishSourceFetch({ok:true,text:async()=>'<script>stale</script>'})")
        assert await page.evaluate(f"!document.querySelector('{panel} .target-code').textContent.includes('<script>stale')")
        await page.evaluate("window.fetch = async () => ({ok:false})")
        await page.click('tbody tr[data-case]:first-child td[data-target="pyjs-js"] button')
        await page.wait_for(f"document.querySelector('{panel} .source-status').textContent.includes('Could not load')", "failed source")
        await page.click(f'{panel} [data-close-source]')
        await page.evaluate("window.fetch = async () => ({ok:true,text:async()=>'<script>source only</script>'})")
        await page.click('tbody tr[data-case]:first-child td[data-target="pyjs-js"] button')
        await page.wait_for(f"document.querySelector('{panel} .target-code').textContent === '<script>source only</script>'", "literal source")
        assert await page.evaluate(f"document.querySelector('{panel} .target-code').children.length") == 0
    finally:
        await page.evaluate("window.fetch = window.savedSourceFetch; delete window.savedSourceFetch; delete window.finishSourceFetch")
    await page.click(cell + ' button')
    await page.set_viewport(390, 844)
    await page.evaluate("""(() => {
      document.querySelector('.table-scroll').scrollLeft = 450;
      window.dispatchEvent(new Event('resize'));
      document.querySelector('.source-row:not([hidden])').scrollIntoView({block:'center'});
    })()""")
    dimensions = await page.evaluate("""(() => {
      const panel = document.querySelector('.source-row:not([hidden]) .source-panel');
      const panes = Array.from(panel.querySelectorAll('.source-split > section')).map(x=>x.getBoundingClientRect());
      const rect = panel.getBoundingClientRect();
      return [rect.left,rect.right,panes[0].width,panes[1].width,panes[0].top,panes[1].top,
        ...Array.from(panel.querySelectorAll('pre')).map(x=>getComputedStyle(x).overflow)];
    })()""")
    assert dimensions[0] >= 0 and dimensions[1] <= 390, dimensions
    assert abs(dimensions[3] / dimensions[2] - 2) < 0.01, dimensions
    assert dimensions[4] == dimensions[5] and dimensions[6:] == ['auto', 'auto'], dimensions
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert await page.evaluate("""Array.from(document.querySelectorAll('.source-row:not([hidden]) pre')).every(pre => {
      pre.scrollLeft = 30;
      return pre.scrollWidth <= pre.clientWidth || pre.scrollLeft > 0;
    })"""), "each code pane scrolls independently"
    await page.screenshot(output / "source-mobile.png")
    # Filtering away the selected target closes the expansion.
    await page.evaluate("""(() => {
      const group = document.querySelector('#group'); group.value = 'jvm';
      group.dispatchEvent(new Event('change'));
    })()""")
    assert await page.evaluate("document.querySelectorAll('.source-row:not([hidden])').length") == 0
    await page.evaluate("""(() => {
      const group = document.querySelector('#group'); group.value = 'all'; group.dispatchEvent(new Event('change'));
      document.querySelector('.table-scroll').scrollLeft = 0;
    })()""")
    await page.set_viewport(1440, 1100)
    # A different row replaces the expansion; filtering it away also closes it.
    await page.click(cell + ' button')
    await page.evaluate("document.querySelectorAll('tbody tr[data-case]')[1].querySelector('.row-source').click()")
    assert await page.evaluate("document.querySelectorAll('.source-row:not([hidden])').length") == 1
    assert await page.evaluate("document.querySelector('.source-row:not([hidden])').previousElementSibling === document.querySelectorAll('tbody tr[data-case]')[1]")
    await page.evaluate("""(() => {
      const select = document.querySelector('#workload');
      const caseName = document.querySelector('.source-row:not([hidden])').dataset.sourceCase;
      select.value = Array.from(select.options).find(option => option.value !== 'all' && option.value !== caseName).value;
      select.dispatchEvent(new Event('change'));
    })()""")
    assert await page.evaluate("document.querySelectorAll('.source-row:not([hidden])').length") == 0
    await page.evaluate("const select = document.querySelector('#workload'); select.value = 'all'; select.dispatchEvent(new Event('change'))")
    await page.click(cell + ' button')
    await page.click(cell + ' button')
    assert await page.evaluate("document.querySelectorAll('.source-row:not([hidden])').length") == 0


async def check(url: str, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    async with Browser() as browser:
        page = await browser.new_page(url)
        # The table is server-rendered before the module installs its handlers.
        # Only Controls.update adds this attribute; do not dispatch into SSR.
        await page.wait_for_selector('td[data-target="cpython"][data-baseline="true"]')
        assert not page.exceptions, page.exceptions
        await page.set_viewport(1440, 1100)
        count = await page.evaluate("document.querySelectorAll('tbody tr[data-case]').length")
        assert count > 0
        assert await page.evaluate("""Array.from(document.querySelectorAll('tbody tr[data-case]')).every(row =>
            row.querySelectorAll('th[scope=row]').length === 1 &&
            row.querySelectorAll('td[data-target]').length === COUNT)""".replace("COUNT", str(len(LABELS))))
        assert await page.evaluate(f"document.querySelectorAll('thead th[scope=col]').length === {len(LABELS) + 1}")
        assert await page.evaluate("Array.from(document.querySelectorAll('.comparison-table thead th[data-target]')).map(item => item.dataset.target)") == list(LABELS)
        # Assert actual values and ratios, not just that a change handler runs.
        for metric, scale, digits in (("startup", 1000, 3), ("memory", 1 / 1024, 2),
                                     ("compile", 1, 3), ("warm", 1000, 3)):
            actual = await page.evaluate(f"""(() => {{
              const select = document.querySelector('#metric');
              select.value = '{metric}'; select.dispatchEvent(new Event('change'));
              return Array.from(document.querySelectorAll('td[data-target]')).map(cell => {{
                return [cell.getAttribute('data-{metric}'), cell.querySelector('.measurement').textContent,
                  cell.dataset.target, cell.dataset.baseline,
                  Array.from(cell.querySelectorAll('.ratio')).map(ratio => {{
                    const reference = cell.parentElement.querySelector('td[data-target="' + ratio.dataset.reference + '"]');
                    return [ratio.dataset.reference, reference?.getAttribute('data-{metric}') || '',
                      ratio.querySelector('.ratio-value').textContent, ratio.dataset.comparison || ''];
                  }})];
              }});
            }})()""")
            for value, display, target, highlighted, ratios in actual:
                assert highlighted == ("true" if target == "cpython" else "false")
                expected_references = [] if target == "cpython" else ["cpython"]
                assert [item[0] for item in ratios] == expected_references
                if not value:
                    assert display == "—"
                else:
                    assert abs(float(display.split()[0]) - float(value) * scale) <= 10 ** -digits
                for _, reference, ratio, comparison in ratios:
                    if value and reference and float(value) > 0 and float(reference) > 0:
                        if float(value) == float(reference):
                            assert ratio == "same" and comparison == ""
                        else:
                            lower = float(value) < float(reference)
                            expected = float(reference) / float(value) if lower else float(value) / float(reference)
                            suffix = ("less memory" if lower else "more memory") if metric == "memory" else ("faster" if lower else "slower")
                            if round(expected, 2) == 1:
                                assert ratio == "≈ same"
                            else:
                                assert ratio.endswith("× " + suffix), ratio
                                assert abs(float(ratio.split("×")[0]) - expected) <= 0.011
                            assert comparison == ("lower" if lower else "higher")
                    else:
                        assert ratio == "—" and comparison == ""
            # Inspect the computed accessibility tree, not merely ARIA markup.
            dom = await page.session.send("DOM.getDocument", {})
            node = await page.session.send("DOM.querySelector", {
                "nodeId": dom["root"]["nodeId"], "selector": "tbody .measurement"})
            tree = await page.session.send("Accessibility.getPartialAXTree", {
                "nodeId": node["nodeId"], "fetchRelatives": False})
            button = next(item for item in tree["nodes"] if item.get("role", {}).get("value") == "button")
            assert button["name"]["value"] == await page.evaluate("document.querySelector('tbody .measurement').textContent")
            assert "View code" in button["description"]["value"]
        await check_comparison_edges(page)
        await check_heatmap(page)
        await check_sources(page, output)
        for group, (_, reference, compiled) in GROUPS.items():
            await page.evaluate("""(() => {
              const select = document.querySelector('#group');
              select.value = GROUP; select.dispatchEvent(new Event('change'));
            })()""".replace("GROUP", json.dumps(group)))
            expected_columns = ["cpython", reference, compiled]
            assert await page.evaluate("Array.from(document.querySelectorAll('.comparison-table thead th[data-target]:not([hidden])')).map(item => item.dataset.target)") == expected_columns
            assert await page.evaluate("""Array.from(document.querySelectorAll('tbody tr[data-case]')).map(row =>
              Array.from(row.querySelectorAll('td[data-target]:not([hidden])')).map(cell => cell.dataset.target))""") == [expected_columns] * count
            assert await page.evaluate("Array.from(document.querySelectorAll('th[scope=colgroup]:not([hidden])')).map(item => [item.dataset.group, item.colSpan])") == [[group, 2]]
            await page.screenshot(output / (group + "-group.png"))
        await page.evaluate("""(() => {
          const select = document.querySelector('#group');
          select.value = 'all'; select.dispatchEvent(new Event('change'));
        })()""")
        await page.evaluate("""(() => {
          const select = document.querySelector('#metric');
          select.value = 'startup'; select.dispatchEvent(new Event('change'));
        })()""")
        await page.wait_for("document.querySelector('.measurement').textContent.includes('ms')", "startup metric")
        cases = await page.evaluate("""Array.from(document.querySelector('#workload').options)
          .map(option => option.value).filter(value => value !== 'all')""")
        for selected_case in cases:
            await page.evaluate("""(() => {
              const select = document.querySelector('#workload');
              select.value = CASE; select.dispatchEvent(new Event('change'));
            })()""".replace("CASE", json.dumps(selected_case)))
            assert await page.evaluate("""Array.from(document.querySelectorAll('tr[data-case]')).every(row =>
              row.hidden === (row.dataset.case !== CASE))""".replace("CASE", json.dumps(selected_case)))
        await page.evaluate("""(() => {
          const select = document.querySelector('#workload');
          select.value = 'all'; select.dispatchEvent(new Event('change'));
          const metric = document.querySelector('#metric');
          metric.value = 'warm'; metric.dispatchEvent(new Event('change'));
        })()""")
        await page.screenshot(output / "desktop.png")
        if "histogram" in cases:
            await page.evaluate("document.querySelector('tr[data-case=histogram]').scrollIntoView({block: 'center'})")
            await page.screenshot(output / "new-workloads.png")
        await page.set_viewport(390, 844)
        assert await page.evaluate("""(() => {
          const scroller = document.querySelector('.table-scroll');
          const label = document.querySelector('tbody th[scope=row]');
          const before = label.getBoundingClientRect().left;
          scroller.scrollLeft = 450;
          return scroller.scrollLeft > 0 && Math.abs(label.getBoundingClientRect().left - before) < 1;
        })()"""), "workload names must stay visible during horizontal scrolling"
        await page.evaluate("window.scrollTo(0, document.querySelector('.table-scroll').getBoundingClientRect().top + scrollY - 16)")
        await page.screenshot(output / "mobile.png")
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        evidence = await page.evaluate("""(() => {
          const panel = Array.from(document.querySelectorAll('details[id]'))
            .find(item => item.querySelector('.trace-table') && item.textContent.includes('JVM compilation'));
          if (!panel) return false;
          panel.open = true;
          panel.scrollIntoView();
          return true;
        })()""")
        if evidence:
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(output / "evidence-mobile.png")
            await page.set_viewport(1440, 1100)
            await page.evaluate("document.querySelector('details[id][open]').scrollIntoView()")
            await page.screenshot(output / "evidence-desktop.png")
        assert not page.exceptions, page.exceptions
        other = await page.evaluate("""Array.from(document.querySelector('#snapshot').options)
            .find(option => !option.selected)?.value || ''""")
        if other:
            await page.evaluate("""(() => {
              const select = document.querySelector('#snapshot');
              select.value = Array.from(select.options).find(option => !option.selected).value;
              select.dispatchEvent(new Event('change'));
            })()""")
            await page.wait_for(f"document.querySelector('#snapshot')?.value === {json.dumps(other)} && location.search.includes({json.dumps(other)})", "snapshot navigation")
            # Partial or unsupported snapshots can legitimately leave the first
            # measurement empty. Wait for client hydration, not a timing value.
            await page.wait_for_selector('td[data-target="cpython"][data-baseline="true"]')
            assert not page.exceptions, page.exceptions
        (output / "result.json").write_text(json.dumps({"rows": count, "runtime_columns": len(LABELS), "filters": cases,
                                                       "target_groups": list(GROUPS), "fixed_baseline": "cpython",
                                                       "heatmap_edges": True, "inline_sources": True,
                                                       "source_request_races": True, "mobile_source_split": "1:2",
                                                       "sticky_workloads": True,
                                                       "snapshot_navigation": bool(other),
                                                       "jit_evidence": evidence,
                                                       "mobile_overflow": False}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="running performance UI, e.g. http://localhost:8000/perf/")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(check(args.url, args.output))


if __name__ == "__main__":
    main()
