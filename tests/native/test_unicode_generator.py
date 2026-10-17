import pytest

from pyjs.native import unicode_data
from scripts.generate_native_unicode import (
    VERSION,
    generate,
    property_ranges,
    render_table,
)


def test_property_generation_handles_comments_ranges_and_other_properties():
    source = """# Derived properties
0041..005A ; Cased # LATIN CAPITAL LETTERS
0061 ; Cased
0300..036F ; Case_Ignorable
"""
    assert property_ranges(source, "Cased") == [(65, 90), (97, 97)]
    assert property_ranges(source, "Case_Ignorable") == [(768, 879)]
    assert property_ranges(source, "Missing") == []
    assert render_table("CASED", property_ranges(source, "Cased")) == [
        "CASED = (", "    (65, 90),", "    (97, 97),", ")", "",
    ]


def test_generation_rejects_a_different_unicode_source():
    with pytest.raises(ValueError, match=f"Expected DerivedCoreProperties-{VERSION}"):
        generate("# DerivedCoreProperties-15.0.0.txt\n")


def test_case_mappings_obey_the_runtime_measurement_overflow_bound():
    for name in ("LOWERCASE", "UPPERCASE", "CASEFOLD", "SWAPCASE", "TITLECASE"):
        mappings = {codepoint: (codepoint + delta,)
                    for start, stop, stride, delta in getattr(unicode_data, name + "_RANGES")
                    for codepoint in range(start, stop + 1, stride or 1)}
        mappings.update(getattr(unicode_data, name + "_SPECIAL"))
        for codepoint, result in mappings.items():
            assert len("".join(map(chr, result)).encode()) <= 3 * len(chr(codepoint).encode())
