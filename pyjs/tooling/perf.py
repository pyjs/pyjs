import asyncio
import contextlib
import inspect
import io
import statistics
import time
import timeit
from dataclasses import dataclass

AUTO_TARGET_SECONDS = 0.05
DEFAULT_SAMPLES = 7
DEFAULT_WARMUPS = 2


class _NullWriter:
    def write(self, value: str) -> int:
        return len(value)

    def flush(self) -> None:
        pass


@dataclass(frozen=True)
class Benchmark:
    loops: int
    samples: tuple[float, ...]

    @property
    def per_loop(self) -> tuple[float, ...]:
        return tuple(sample / self.loops for sample in self.samples)

    def json(self) -> dict:
        values = self.per_loop
        return {
            "loops": self.loops,
            "samples": list(values),
            "median": statistics.median(values),
            "mean": statistics.mean(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
        }


def run_python(function) -> tuple[str, str, BaseException | None]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    error = None
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = function()
            if inspect.isawaitable(result):
                asyncio.run(result)
    except BaseException as caught:
        error = caught
    return stdout.getvalue(), stderr.getvalue(), error


def benchmark_python(function, *, loops: int | None, samples: int, warmups: int) -> Benchmark:
    output = _NullWriter()
    if inspect.iscoroutinefunction(function):
        return _benchmark_async(
            function, loops=loops, samples=samples, warmups=warmups, output=output
        )

    timer = timeit.Timer(function)
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        if loops is None:
            loops = _calibrate(lambda count: timer.timeit(number=count))
        for _ in range(warmups):
            timer.timeit(number=loops)
        values = tuple(timer.repeat(repeat=samples, number=loops))
    return Benchmark(loops, values)


def calibrate_python(function) -> int:
    output = _NullWriter()
    if inspect.iscoroutinefunction(function):
        return _benchmark_async(function, loops=None, samples=0, warmups=0, output=output).loops
    timer = timeit.Timer(function)
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        return _calibrate(lambda count: timer.timeit(number=count))


def _calibrate(measure) -> int:
    loops = 1
    scale = (2, 5, 10)
    index = 0
    while True:
        if measure(loops) >= AUTO_TARGET_SECONDS and measure(loops) >= AUTO_TARGET_SECONDS:
            return loops
        magnitude, factor = divmod(index, len(scale))
        loops = scale[factor] * 10**magnitude
        index += 1


def _benchmark_async(function, *, loops, samples, warmups, output) -> Benchmark:
    async def repeat(count):
        for _ in range(count):
            await function()

    def measure(count):
        started = time.perf_counter()
        asyncio.run(repeat(count))
        return time.perf_counter() - started

    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        if loops is None:
            loops = _calibrate(measure)
        for _ in range(warmups):
            measure(loops)
        values = tuple(measure(loops) for _ in range(samples))
    return Benchmark(loops, values)


def javascript_benchmark(source: str, *, is_async: bool, loops, samples: int, warmups: int) -> str:
    loops_source = "null" if loops is None else str(loops)
    await_source = "await " if is_async else ""
    return (
        source
        + f"""
const __pyjsPerf__ = async () => {{
  const call = __pyjsEntry__.main;
  const output = console.log;
  console.log = () => {{}};
  let blackhole;
  const measure = async (loops) => {{
    const started = process.hrtime.bigint();
    for (let index = 0; index < loops; index += 1) {{
      blackhole = {await_source}call();
    }}
    return Number(process.hrtime.bigint() - started) / 1e9;
  }};
  let loops = {loops_source};
  if (loops === null) {{
    loops = 1;
    let confirmations = 0;
    while (confirmations < 2) {{
      if (await measure(loops) >= {AUTO_TARGET_SECONDS}) {{
        confirmations += 1;
      }} else {{
        loops *= 2;
        confirmations = 0;
      }}
    }}
  }}
  for (let index = 0; index < {warmups}; index += 1) {{
    await measure(loops);
  }}
  const values = [];
  for (let index = 0; index < {samples}; index += 1) {{
    values.push(await measure(loops));
  }}
  console.log = output;
  process.stdout.write("__PYJS_PERF__" + JSON.stringify({{loops, values}}) + "\\n");
  globalThis.__pyjsBlackhole__ = blackhole;
}};
__pyjsPerf__().catch((error) => {{
  console.error(error);
  process.exitCode = 1;
}});
"""
    )
