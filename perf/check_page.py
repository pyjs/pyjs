"""Exercise the live PyJS UI with an owned managed Chrome."""
import argparse
import asyncio
import json
from pathlib import Path

from perf.view import LABELS
from pyjs.tooling.browser import Browser


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
        # Assert actual values and ratios, not just that a change handler runs.
        for metric, scale, digits in (("startup", 1000, 3), ("memory", 1 / 1024, 2),
                                     ("compile", 1, 3), ("warm", 1000, 3)):
            actual = await page.evaluate(f"""(() => {{
              const select = document.querySelector('#metric');
              select.value = '{metric}'; select.dispatchEvent(new Event('change'));
              const baseline = document.querySelector('#baseline');
              baseline.value = 'java'; baseline.dispatchEvent(new Event('change'));
              return Array.from(document.querySelectorAll('td[data-target]')).map(cell => {{
                const reference = cell.parentElement.querySelector('td[data-target=java]');
                return [cell.getAttribute('data-{metric}'), cell.querySelector('.measurement').textContent,
                  reference?.getAttribute('data-{metric}') || '', cell.querySelector('.ratio').textContent,
                  cell.dataset.target, cell.dataset.baseline];
              }});
            }})()""")
            for value, display, reference, ratio, target, highlighted in actual:
                assert highlighted == ("true" if target == "java" else "false")
                if not value:
                    assert display == ratio == "—"
                else:
                    assert abs(float(display.split()[0]) - float(value) * scale) <= 10 ** -digits
                    if reference and float(value) > 0 and float(reference) > 0:
                        if target == "java":
                            assert ratio == "baseline"
                        elif float(value) == float(reference):
                            assert ratio == "same as baseline"
                        else:
                            lower = float(value) < float(reference)
                            expected = float(reference) / float(value) if lower else float(value) / float(reference)
                            suffix = ("less memory" if lower else "more memory") if metric == "memory" else ("faster" if lower else "slower")
                            assert ratio.endswith("× " + suffix), ratio
                            assert abs(float(ratio.split("×")[0]) - expected) <= 0.011
                    else:
                        assert ratio == "—"
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
          const baseline = document.querySelector('#baseline');
          baseline.value = 'cpython'; baseline.dispatchEvent(new Event('change'));
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
            await page.wait_for("document.querySelector('.measurement').textContent !== '—'", "snapshot controls initialized")
            assert not page.exceptions, page.exceptions
        (output / "result.json").write_text(json.dumps({"rows": count, "runtime_columns": len(LABELS), "filters": cases,
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
