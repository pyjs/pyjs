"""Exercise the live PyJS UI with an owned managed Chrome."""
import argparse
import asyncio
import json
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
        await check_comparison_edges(page)
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
