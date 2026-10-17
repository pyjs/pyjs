import json
import math
import struct

import pytest

from pyjs import float32, int64, uint32
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_float_notation_boundaries_agree_across_strings_and_json(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json
        def render(values: list[float]) -> str:
            strings: list[str] = []
            representations: list[str] = []
            formatted: list[str] = []
            keys: dict[float, float] = {}
            for value in values:
                strings.append(str(value))
                representations.append(repr(value))
                formatted.append(f"{value}")
                keys[value] = value
            return json.dumps((values, strings, representations, formatted, keys))
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        values = [math.nextafter(1e-4, 0.0), math.nextafter(1e16, 0.0),
                  0.0, -0.0, 5e-324, -5e-324, math.inf, -math.inf, math.nan]
        for exponent in range(-323, 309):
            boundary = float(f"1e{exponent}")
            for value in (math.nextafter(boundary, 0.0), boundary, math.nextafter(boundary, math.inf)):
                values.extend((value, -value))
        bits = 0x6A09E667F3BCC909
        for _ in range(256):
            bits = (bits * 0x5851F42D4C957F2D + 1) & ((1 << 64) - 1)
            values.append(struct.unpack(">d", bits.to_bytes(8, "big"))[0])
        # One compilation covers all decimal boundaries and sampled binary64
        # values; small batches keep a mismatch local and readable.
        for start in range(0, len(values), 64):
            batch = values[start:start + 64]
            expected = json.dumps((batch, [str(value) for value in batch],
                [repr(value) for value in batch], [f"{value}" for value in batch],
                {value: value for value in batch}))
            assert library.render(batch) == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_preserves_every_portable_numeric_representation(optimize):
    comparison = LLVM().assert_matches_python('''
        import json
        from pyjs import (
            int8, uint8, int16, uint16, int32, uint32, int64, float32, float64,
        )

        class Metrics:
            def __init__(self):
                self.count = uint32(4294967295)
                self.ratio = float32(0.1)

        def main() -> str:
            metrics = Metrics()
            values: list[float32 | None] = [float32(2.675), None, float32(-0.0)]
            mapping: dict[uint32, float32] = {metrics.count: metrics.ratio}
            return json.dumps((
                int8(130), uint8(257), int16(32768), uint16(65537),
                int32(2147483648), uint32(4294967295),
                int64(9007199254740993), int64(-9223372036854775808),
                float32(0.1), float64(-0.0), metrics.count, metrics.ratio,
                values, mapping,
            ), allow_nan=False)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.matches
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_marshaled_portable_numbers_and_strict_float_errors(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json
        from pyjs import float32, int64, uint32

        def render(counts: list[int64], samples: dict[uint32, float32]) -> str:
            try:
                return json.dumps((counts, samples), allow_nan=False)
            except ValueError:
                return "nonfinite sample"
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        counts = [int64(9007199254740993), int64(-9223372036854775808)]
        samples = {uint32(4294967295): float32(0.1), uint32(0): float32(-0.0)}
        expected = json.dumps((counts, samples), allow_nan=False)
        assert library.render(counts, samples) == expected
        assert library.render(counts, {uint32(1): float32(float("inf"))}) == "nonfinite sample"
        assert library.render(counts, samples) == expected
    finally:
        library.close()
