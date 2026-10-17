import pytest

from pyjs.tooling.perf import (
    Benchmark,
    _calibrate,
    benchmark_python,
    javascript_benchmark,
)


def test_benchmark_reports_per_loop_samples_and_summary():
    result = Benchmark(10, (0.1, 0.2, 0.3)).json()

    assert result["samples"] == pytest.approx([0.01, 0.02, 0.03])
    assert result["median"] == pytest.approx(0.02)
    assert result["mean"] == pytest.approx(0.02)
    assert result["min"] == pytest.approx(0.01)
    assert result["max"] == pytest.approx(0.03)


def test_python_benchmark_uses_requested_shape_and_suppresses_output(capsys):
    result = benchmark_python(lambda: print("ignored"), loops=2, samples=3, warmups=1)

    assert result.loops == 2
    assert len(result.samples) == 3
    assert capsys.readouterr().out == ""


def test_calibration_stops_at_the_short_default_budget():
    measurements = []

    def measure(loops):
        measurements.append(loops)
        return loops / 1000

    assert _calibrate(measure) == 50
    assert measurements == [1, 2, 5, 10, 20, 50, 50]


def test_javascript_benchmark_awaits_async_entries_and_emits_machine_marker():
    source = javascript_benchmark(
        "const __pyjsEntry__ = {main: async () => 1};\n",
        is_async=True,
        loops=5,
        samples=3,
        warmups=1,
    )

    assert "blackhole = await call();" in source
    assert "let loops = 5;" in source
    assert "confirmations < 2" in source
    assert 'process.stdout.write("__PYJS_PERF__"' in source
