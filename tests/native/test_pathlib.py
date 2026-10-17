from pyjs.tooling.llvm import LLVM


def test_llvm_pure_paths_compose_application_and_log_locations():
    LLVM().assert_matches_python("""
        import pathlib
        from pathlib import PurePosixPath

        def main() -> str:
            first = PurePosixPath("/srv", "./apps", "sample-app", "settings.tar.gz")
            joined = first.parent / "logs" / "today.json"
            relative = pathlib.PurePath("a//b", "../c.txt")
            return "|".join((
                str(first), first.name, first.stem, first.suffix,
                ",".join(first.suffixes), ",".join(first.parts),
                str(joined), str(relative), str(relative.parent),
                str(first.is_absolute()), first.with_suffix(".json").as_posix(),
                first.with_stem("archive").as_posix(),
                str(PurePosixPath(first.parent, "other", PurePosixPath("file"))),
                str("prefix" / relative),
                str(hash(relative) == hash(PurePosixPath("a/b/../c.txt"))),
            ))
    """)


def test_llvm_pure_paths_preserve_roots_dotfiles_and_component_ordering():
    LLVM().assert_matches_python("""
        from pathlib import PurePosixPath

        def main() -> str:
            result: list[str] = []
            for source in [
                "", ".", "..", "/", "//", "///", "//srv//./file",
                "a//b/../c", ".hidden", ".config.tar.gz", "..name.ext",
                "a.", "a..", "a..b", "a...b.", "....",
            ]:
                path = PurePosixPath(source)
                result.append(str((
                    str(path), repr(path), path.parts, path.drive,
                    path.root, path.anchor, path.name, path.stem,
                    path.suffix, path.suffixes, str(path.parent),
                    str(path.joinpath("child", "/reset", "./leaf")),
                )))
            left = PurePosixPath("a/z")
            right = PurePosixPath("a.b")
            result.append(str((left < right, left <= right, left > right,
                               left >= right, left == PurePosixPath("a/./z"))))
            return "|".join(result)
    """)


def test_pure_path_ordering_uses_split_text_including_anchors_and_dot():
    result = LLVM().assert_matches_python('''
        from pathlib import PurePosixPath
        def main() -> str:
            values = ["/x", "-y", "//a", "/b", "a/b", "a.b", ".", "-", "", "/", "//"]
            result: list[str] = []
            for left in values:
                for right in values:
                    a, b = PurePosixPath(left), PurePosixPath(right)
                    result.append(str((a < b, a <= b, a > b, a >= b, a == b)))
            return "|".join(result)
    ''', sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_llvm_pure_path_edits_validate_names_and_suffixes():
    LLVM().assert_matches_python("""
        from pathlib import PurePosixPath

        def main() -> str:
            result: list[str] = []
            for source in ["file.tar.gz", ".hidden", "a.", "/", "."]:
                path = PurePosixPath(source)
                for name in ["", ".", "..", "new.ext", "a/b"]:
                    try:
                        result.append(str(path.with_name(name)))
                    except ValueError as error:
                        result.append(str(error))
                    try:
                        result.append(str(path.with_stem(name)))
                    except ValueError as error:
                        result.append(str(error))
                for suffix in ["", ".", ".txt", "txt", ".a/b"]:
                    try:
                        result.append(str(path.with_suffix(suffix)))
                    except ValueError as error:
                        result.append(str(error))
            return "|".join(result)
    """)


def test_llvm_pure_paths_compute_lexical_ancestors_and_relative_locations():
    LLVM().assert_matches_python("""
        from pathlib import PurePath, PurePosixPath
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            output: list[str] = []
            for source in ["a/b/c", "/a/b", "//a/b", "a/../b", ".", "/"]:
                path = PurePath(source)
                parents = path.parents
                gc_collect()
                output.append(str(tuple(str(parent) for parent in parents)))
                if parents:
                    output.append(str(parents[-1]))
                for base in [".", "a", "a/b", "a/../c", "/a", "//a", "../x"]:
                    output.append(str(path.is_relative_to(base)))
                    for walk in (False, True):
                        try:
                            result = path.relative_to(PurePosixPath(base), walk_up=walk)
                            output.append(str(result))
                        except ValueError as error:
                            output.append(str(error))
            return "|".join(output)
    """)
