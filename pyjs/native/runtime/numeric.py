"""Scalar conversion and arithmetic LLVM runtime."""

import textwrap
from functools import cache

from ..unicode_data import DECIMAL_RANGES

# Unlike str.isspace(), numeric parsing excludes the ASCII record separators.
WHITESPACE = "\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


@cache
def compiled_integer_parser_runtime() -> tuple[str, ...]:
    from . import algorithms, numeric_text
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.int.from.string.into": numeric_text.parse_integer,
        "pyjs.unicode.decimal.value.with.table": numeric_text.decimal_value,
    }, dependencies={
        "pyjs.utf8.decode.scalar": algorithms.decode_utf8,
    })


def integer_string_runtime() -> list[str]:
    return [
        *compiled_integer_parser_runtime(),
        *textwrap.dedent(f"""
            define i32 @pyjs.unicode.decimal.value(i32 %codepoint) {{
              %result = call i32 @pyjs.unicode.decimal.value.with.table(
                  i32 %codepoint, ptr @pyjs.unicode.decimal, i64 {len(DECIMAL_RANGES)})
              ret i32 %result
            }}

            define {{ i8, i64 }} @pyjs.int.from.string(ptr %text, i64 %base, ptr %whitespace) {{
              %output = alloca i64
              store i64 0, ptr %output
              %status = call i8 @pyjs.int.from.string.into(
                  ptr %text, i64 %base, ptr %whitespace, ptr @pyjs.unicode.decimal,
                  i64 {len(DECIMAL_RANGES)}, ptr %output)
              %value = load i64, ptr %output
              %present = insertvalue {{ i8, i64 }} poison, i8 %status, 0
              %result = insertvalue {{ i8, i64 }} %present, i64 %value, 1
              ret {{ i8, i64 }} %result
            }}
        """).strip().splitlines(),
    ]


@cache
def compiled_float_parser_runtime() -> tuple[str, ...]:
    from . import algorithms, arena, numeric_text
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.float.from.string.into": numeric_text.parse_float,
    }, dependencies={
        "pyjs.unicode.decimal.value.with.table": numeric_text.decimal_value,
        "pyjs.utf8.decode.scalar": algorithms.decode_utf8,
        "pyjs.arena.try.alloc": arena.allocate_in_arena,
    })


def float_string_parser_runtime() -> list[str]:
    return [
        *compiled_float_parser_runtime(),
        *textwrap.dedent(f"""
            define {{ i8, double }} @pyjs.float.from.string(ptr %arena, ptr %text, ptr %whitespace) {{
              %output = alloca double
              store double 0.0, ptr %output
              %valid = call i8 @pyjs.float.from.string.into(
                  ptr %arena, ptr %text, ptr %whitespace, ptr @pyjs.unicode.decimal,
                  i64 {len(DECIMAL_RANGES)}, ptr %output)
              %value = load double, ptr %output
              %present = insertvalue {{ i8, double }} poison, i8 %valid, 0
              %result = insertvalue {{ i8, double }} %present, double %value, 1
              ret {{ i8, double }} %result
            }}
        """).strip().splitlines(),
    ]

@cache
def compiled_integer_runtime(include_true_division: bool, include_modular_pow: bool) -> tuple[str, ...]:
    from . import integer_math as m
    from .compiler import compile_runtime

    roots = {
        "pyjs.int.round.digits": m.round_digits,
        "pyjs.int.round.wide": m.round_wide,
        "pyjs.int.reject.negative.shift": m.reject_negative_shift,
        "pyjs.int.divmod.into": m.divmod_into,
        "pyjs.int.pow": m.power,
        "pyjs.int.bit_count": m.bit_count,
        "pyjs.int.bit_length": m.bit_length,
    }
    if include_true_division:
        roots["pyjs.int.true.divide"] = m.true_divide
    if include_modular_pow:
        roots["pyjs.int.pow.modular.into"] = m.modular_power
    return compile_runtime(roots)


def integer_runtime(
    include_true_division: bool = True,
    *,
    include_modular_pow: bool = False,
) -> list[str]:
    result = [
        "declare void @llvm.trap()",
        "declare i64 @llvm.ctlz.i64(i64, i1 immarg)",
        "declare i64 @llvm.ctpop.i64(i64)",
        *compiled_integer_runtime(include_true_division, include_modular_pow),
    ]
    for name, wrapped in (("int", "false"), ("fixed.int", "true")):
        result.extend(textwrap.dedent(f"""
            define {{ i64, i64 }} @pyjs.{name}.divmod(i64 %left, i64 %right) {{
              %output = alloca {{ i64, i64 }}
              call void @pyjs.int.divmod.into(
                  i64 %left, i64 %right, i1 {wrapped}, ptr %output)
              %result = load {{ i64, i64 }}, ptr %output
              ret {{ i64, i64 }} %result
            }}
        """).strip().splitlines())
    if include_modular_pow:
        result.extend(textwrap.dedent("""
            define { i1, i64 } @pyjs.int.pow.modular(i64 %base, i64 %exponent, i64 %modulus) {
              %output = alloca i64
              store i64 0, ptr %output
              %valid = call i1 @pyjs.int.pow.modular.into(
                  i64 %base, i64 %exponent, i64 %modulus, ptr %output)
              %value = load i64, ptr %output
              %present = insertvalue { i1, i64 } poison, i1 %valid, 0
              %result = insertvalue { i1, i64 } %present, i64 %value, 1
              ret { i1, i64 } %result
            }
        """).strip().splitlines())
    return result

@cache
def compiled_float_runtime() -> tuple[str, ...]:
    from . import float_math
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.float.divide": float_math.divide,
        "pyjs.float.integer.equal": float_math.integer_equal,
        "pyjs.float.integer.order": float_math.integer_order,
        "pyjs.float.round.digits": float_math.round_digits,
        "pyjs.float.divmod.into": float_math.divmod_into,
    })


def float_runtime(declare_formatting: bool = True) -> list[str]:
    return [
        '@pyjs.float.round.format = private constant [5 x i8] c"%.*f\\00"',
        "declare double @fmod(double, double)",
        "declare double @llvm.fabs.f64(double)",
        "declare double @llvm.floor.f64(double)",
        "declare double @llvm.roundeven.f64(double)",
        "declare double @llvm.copysign.f64(double, double)",
        "declare double @strtod(ptr, ptr)",
        *(
            [
                "declare i32 @snprintf(ptr, i64, ptr, ...)",
            ]
            if declare_formatting
            else []
        ),
        "",
        *compiled_float_runtime(),
        *textwrap.dedent("""
            define { double, double } @pyjs.float.divmod(double %left, double %right) {
              %output = alloca { double, double }
              call void @pyjs.float.divmod.into(double %left, double %right, ptr %output)
              %result = load { double, double }, ptr %output
              ret { double, double } %result
            }
        """).strip().splitlines(),
    ]

@cache
def compiled_float_text_runtime() -> tuple[str, ...]:
    from . import float_text, text_operations
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.string.from.f64": float_text.from_float,
        "pyjs.string.format.f64": float_text.format_float,
    }, dependencies={"pyjs.string.new.owned": text_operations.new_owned})


def float_string_runtime() -> list[str]:
    return [
        '@pyjs.string.float.general = private constant [5 x i8] c"%.*g\\00"',
        '@pyjs.string.float.scientific = private constant [5 x i8] c"%.*e\\00"',
        *compiled_float_text_runtime(),
    ]
