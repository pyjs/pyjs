import pytest

from pyjs.tooling.llvm import LLVM, _address_sanitized_ir


def test_asan_marks_multiline_aggregate_and_quoted_function_headers():
    source = '''declare ptr @malloc(i64)
define { i64, ptr } @"name(with)parens"(
  ptr byval({ i64, ptr }) %"arg)name", i64 %count
) #0 { ret { i64, ptr } zeroinitializer }
define i32 @main() { ret i32 0 }
attributes #0 = { nounwind }
'''
    assert _address_sanitized_ir(source) == '''declare ptr @malloc(i64)
define { i64, ptr } @"name(with)parens"(
  ptr byval({ i64, ptr }) %"arg)name", i64 %count
) sanitize_address #0 { ret { i64, ptr } zeroinitializer }
define i32 @main() sanitize_address { ret i32 0 }
attributes #0 = { nounwind }
'''


@pytest.mark.parametrize("header", ["define unfamiliar header", "define i32 @next unexpected",
                                     "define unfamiliar define i32 @next() { ret i32 0 }"])
def test_asan_rejects_unrecognized_headers_instead_of_silently_skipping_them(header):
    with pytest.raises(ValueError, match="cannot locate every LLVM function"):
        _address_sanitized_ir("define i32 @first() { ret i32 0 } " + header)


def test_asan_rejects_unterminated_parameters():
    with pytest.raises(ValueError, match="unterminated LLVM function parameters"):
        _address_sanitized_ir("define i32 @main(ptr byval(i32) %value")


def test_asan_keyword_scanning_ignores_comments_strings_and_identifiers():
    source = r'''; define i32 @comment() ( )
@text = constant [7 x i8] c"define\00"
@define = global i32 1
@slash = constant [1 x i8] c"\"
define i32 @"define()" ; define @fake(
(i32 %define) { define: ret i32 %define }
@"tail\" = global i32 0
'''
    assert _address_sanitized_ir(source) == source.replace(
        '(i32 %define) {', '(i32 %define) sanitize_address {')


@pytest.mark.parametrize("tail,expected", [
    ("nounwind", " sanitize_address nounwind"),
    ("comdat($main)", " sanitize_address comdat($main)"),
    ('section".text.x"', ' sanitize_address section".text.x"'),
    ("addrspace(0)nounwind", "addrspace(0) sanitize_address nounwind"),
])
def test_asan_separates_adjacent_function_attributes(tail, expected):
    source = f"define i32 @main(){tail} {{ ret i32 0 }}"
    assert _address_sanitized_ir(source) == f"define i32 @main(){expected} {{ ret i32 0 }}"


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("spacing,separator,qualifier", [
    ("", "\n", ""), (" ", "\n", ""), ("\n  ", "\n", ""), ("", " ", ""),
    ("", " ; ignored define @fake(\n", ""), ("", "\n", " unnamed_addr"),
    ("", "\n", " local_unnamed_addr #0"), ("", "\n", " unnamed_addr addrspace(0)"),
    ("", '\n@s = global [1 x i8] c"\\"\n', ""),
    ("", '\n@"a\\" = global i32 0\n', ""), ("", "\n@g = global i32 0", ""),
    ("", "\n@0 = global i32 0\n@g = global ptr @0", ""),
    ("", "\n@e = external global i32", ""),
    ("", "\n@e = external global i8", ""),
    ("", "\n", " ; keep unnamed_addr\n"),
    ("", "\n", " ; documented addrspace(0)\n #0"),
    ("", "\n", " ; ignored qualifier\n local_unnamed_addr ; comment\n addrspace(0)"),
    ("", "\n", "nounwind"), ("", "\n", "comdat($main)"),
    ("", "\n", 'section".text.x"'), ("", "\n", "addrspace(0)nounwind"),
])
def test_asan_instruments_generated_ir_memory_accesses(tmp_path, optimize, spacing, separator, qualifier):
    source = '''
declare ptr @malloc(i64)
declare void @free(ptr)
define i32 @main() {
  %data = call ptr @malloc(i64 1)
  %past = getelementptr i8, ptr %data, i64 8
  store volatile i8 42, ptr %past
  call void @free(ptr %data)
  ret i32 0
}
'''
    source = source.replace("@main()", f"@main{spacing}(){qualifier}")
    source = source.replace("@free(ptr)\ndefine", f"@free(ptr){separator}define")
    source += '\nattributes #0 = { nounwind }\n@tail = global [1 x i8] c"x"\n'
    source += '$main = comdat any\n'
    execution = LLVM()._run_ir(source, tmp_path, name="asan-probe", optimize=optimize,
                               pass_fds=(), sanitizers=("address",), timeout=10, artifacts=tmp_path)
    assert execution.returncode != 0
    assert "AddressSanitizer: heap-buffer-overflow" in execution.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind,returned", [("void", ""), ("ptr", " null")])
def test_asan_marks_glued_return_type_not_a_call_in_the_body(tmp_path, optimize, kind, returned):
    source = f'''
declare ptr @malloc(i64)
declare void @free(ptr)
define {kind}@overflow() {{
  %data = call ptr @malloc(i64 1)
  %past = getelementptr i8, ptr %data, i64 8
  store volatile i8 42, ptr %past
  call void @free(ptr %data)
  ret {kind}{returned}
}}
define i32 @main() {{
  call {kind} @overflow()
  ret i32 0
}}
'''
    assert _address_sanitized_ir(source) == source.replace(
        "@overflow() {", "@overflow() sanitize_address {").replace(
        "@main() {", "@main() sanitize_address {")
    execution = LLVM()._run_ir(source, tmp_path, name="asan-sigil", optimize=optimize,
                               pass_fds=(), sanitizers=("address",), timeout=10, artifacts=tmp_path)
    assert execution.returncode != 0
    assert "AddressSanitizer: heap-buffer-overflow" in execution.stderr
