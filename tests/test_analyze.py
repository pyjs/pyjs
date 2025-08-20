from pyjs.testing import BaseTestCase


class TestAnalyzeAssignments(BaseTestCase):

    def test_basic_assignment(self):
        self.a("a = 9", "a: int = 9")
        self.a(
            "a = b = c = 9",
            """
            c: int = 9
            b: int = c
            a: int = b
            """
        )

    def test_reassignment(self):
        self.a(
            "a = 9;a = b = 10",
            """
            a: int = 9
            b: int = 10
            a = b
            """
        )

    def test_annotated_types(self):
        self.a("b: str=''", "b: str = ''")
        self.a("c: list[str]=[]", "c: list[str] = []")
        self.a("c: list[int|list[int]]=[]", "c: list[int | list[int]] = []")
        self.a("d: dict[str,str|int]={}", "d: dict[str, str | int] = {}")

    def test_inferred_types(self):
        self.a("b=''", "b: str = ''")
        self.a("c=['']", "c: list[str] = ['']")
        self.a("c=[9,[10]]", "c: list[int | list[int]] = [9, [10]]")
        self.a(
            "d={'foo': 'baz', 'bar': 9}",
            "d: dict[str, str | int] = {'foo': 'baz', 'bar': 9}"
        )

    def test_incomplete_info(self):
        with self.assertRaisesRegex(
            TypeError,
            "Concrete type could not be determined "
            "from type annotation or value."
        ):
            self.a("c=[]", "")


class TestAnalyzeFunctions(BaseTestCase):

    def test_returns_None(self):
        self.a(
            """
            def main():
                return
            """,
            """
            def main():
                return
            """
        )
        self.a(
            """
            @js
            class Foo:
                def main(self):
                    return
            def main():
                Foo().main()
            """,
            """
            class Foo:

                def main():
                    return

            def main():
                Foo().[Foo]main()
            """
        )

    def test_inferred(self):
        self.a(
            """
            def main(n = 1):
                return n + n
            """,
            """
            def main(n: int=1) -> int:
                return n.[int]__add__!(n)
            """
        )
        self.a(
            """
            @js
            class Foo:
                def main(self, n=1):
                    return n+n
            def main():
                a = Foo().main()
            """,
            """
            class Foo:

                def main(n: int=1) -> int:
                    return n.[int]__add__!(n)

            def main():
                a: int = Foo().[Foo]main()
            """
        )

    def test_annotated(self):
        self.a(
            """
            def main(n: int):
                return n + n
            """,
            """
            def main(n: int) -> int:
                return n.[int]__add__!(n)
            """
        )
        self.a(
            """
            @js
            def foo() -> int:
                pass
            def main():
                a = foo()
            """,
            """
            def foo() -> int:
                pass

            def main():
                a: int = foo()
            """
        )

    def test_incomplete_info(self):
        with self.assertRaisesRegex(
                TypeError,
                "Concrete type could not be determined "
                "from type annotation or value."
        ):
            self.a(
                """
                def main(n):
                    return n + n
                """,
                """
                """
            )


class TestAnalyzeComparators(BaseTestCase):

    def test_int_comparators(self):
        tests = {
            "<": "__lt__",
            "<=": "__le__",
            ">": "__gt__",
            ">=": "__ge__",
            "==": "__eq__",
            "!=": "__ne__",
        }
        for py_op, func_op in tests.items():
            with self.subTest(f"{py_op} : {func_op}"):
                self.a(
                    f"a = 1;b = 2;c = a {py_op} b",
                    f"""
                    a: int = 1
                    b: int = 2
                    c: bool = a.[int]{func_op}!(b)
                    """
                )

    def test_overloaded_comparators(self):
        tests = {
            "<": ("__lt__", "__gt__"),
            "<=": ("__le__", "__ge__"),
            ">": ("__gt__", "__lt__"),
            ">=": ("__ge__", "__le__"),
            "==": ("__eq__", "__eq__"),
            "!=": ("__ne__", "__ne__"),
        }
        for py_op, (func_op, _) in tests.items():
            with self.subTest(f"{py_op} : {func_op}"):
                self.a(
                    f"""
                    @js
                    class B:
                      pass
                    @js
                    class A:
                      def {func_op}(self, other: B) -> bool:
                        pass
                    @js
                    def main():
                        a = A();b = B();c = a {py_op} b
                    """,
                    f"""
                    class B:

                    class A:

                        def {func_op}(other: B) -> bool:
                            pass

                    def main():
                        a: A = A()
                        b: B = B()
                        c: bool = a.[A]{func_op}(b)
                    """
                )
        for py_op, (_, func_op) in tests.items():
            with self.subTest(f"(swapped) {py_op} : {func_op}"):
                self.a(
                    f"""
                    @js
                    class A:
                      pass
                    @js
                    class B:
                      def {func_op}(self, other: A) -> bool:
                        pass
                    @js
                    def main():
                        a = A();b = B();c = a {py_op} b
                    """,
                    f"""
                    class A:

                    class B:

                        def {func_op}(other: A) -> bool:
                            pass

                    def main():
                        a: A = A()
                        b: B = B()
                        c: bool = b.[B]{func_op}(a)
                    """
                )


class TestAnalyzeOperators(BaseTestCase):

    def test_int_operators(self):
        tests = {
            "+": "__add__",
            "-": "__sub__",
            "*": "__mul__",
            "/": "__truediv__",
            "//": "__floordiv__",
            "**": "__mod__",
        }
        for py_op, func_op in tests.items():
            with self.subTest(f"{py_op} : {func_op}"):
                self.a(
                    f"a = 1;b = 2;c = a {py_op} b",
                    f"""
                    a: int = 1
                    b: int = 2
                    c: int = a.[int]{func_op}!(b)
                    """
                )

    def test_str_operators(self):
        self.a(
            f"a = 'a';b = a * 3;c = 3 * a",
            f"""
            a: str = 'a'
            b: str = a.[str]__mul__!(3)
            c: str = a.[str]__rmul__!(3)
            """
        )
        self.a(
            f"a = 'a';b = a + 'b';",
            f"""
            a: str = 'a'
            b: str = a.[str]__add__!('b')
            """
        )

    def test_overloaded_operators(self):
        tests = {
            "+": ("__add__", "__radd__"),
            "-": ("__sub__", "__rsub__"),
            "*": ("__mul__", "__rmul__"),
            "/": ("__truediv__", "__rtruediv__"),
            "//": ("__floordiv__", "__rfloordiv__"),
            "**": ("__mod__", "__rmod__"),
        }
        for py_op, (left_func, right_func) in tests.items():
            with self.subTest(f"{py_op} : {left_func}"):
                self.a(
                    f"""
                    @js
                    class B:
                        def {right_func}(self, other: str):
                          return other
                    @js
                    class A:
                        def {left_func}(self, other: B):
                          return self
                    @js
                    def main():
                        a = A();b = B();c = a {py_op} b
                    """,
                    f"""
                    class B:

                    class A:

                        def {left_func}(other: B) -> A:
                            return self

                    def main():
                        a: A = A()
                        b: B = B()
                        c: A = a.[A]{left_func}(b)
                    """
                )
            with self.subTest(f"{py_op} : {right_func}"):
                # left side has the correct function but it accepts
                # wrong argument type (str), therefore right
                # func should be used instead
                self.a(
                    f"""
                    @js
                    class A:
                      def {left_func}(self, other: str):
                        return self
                    @js
                    class B:
                      def {right_func}(self, other: A):
                        return other
                    @js
                    def main():
                        a = A();b = B();c = a {py_op} b
                    """,
                    f"""
                    class A:

                    class B:

                        def {right_func}(other: A) -> A:
                            return other

                    def main():
                        a: A = A()
                        b: B = B()
                        c: A = b.[B]{right_func}(a)
                    """
                )


class TestAnalyzeLoops(BaseTestCase):

    def test_basic_for_loop(self):
        self.a(
            """
            def main():
                l = ["a", "b", "c"]
                for i in l:
                    x = i
            """,
            """
            def main():
                l: list[str] = ['a', 'b', 'c']
                for i: str in l:
                    x: str = i
            """
        )
        self.a(
            """
            @js
            def foo():
                return ["a", "b", "c"]
            def main():
                for i in foo():
                    x = i
            """,
            """
            def foo() -> list[str]:
                return ['a', 'b', 'c']

            def main():
                for i: str in foo():
                    x: str = i
            """
        )

    def test_destructuring_tuples_for_loop(self):
        self.a(
            """
            def main():
                l = [("a", 1, ["a"]), ("b", 2, ["b"]), ("c", 3, ["c"])]
                for a, b, c in l:
                    x = a
                    y = b
                    for d in c:
                        zz = d
                    z = c
            """,
            """
            def main():
                l: list[tuple[str, int, list[str]]] = [('a', 1, ['a']), ('b', 2, ['b']), ('c', 3, ['c'])]
                for a: str, b: int, c: list[str] in l:
                    x: str = a
                    y: int = b
                    for d: str in c:
                        zz: str = d
                    z: list[str] = c
            """
        )

    def test_destructuring_dict_for_loop(self):
        self.a(
            """
            def main():
                l = {"a": {"aa": 1}}
                for a, b in l.items():
                    x = a
                    y = b
                    for d in b.keys():
                        key = d
                    for c in b.values():
                        value = c
            """,
            """
            def main():
                l: dict[str, dict[str, int]] = {'a': {'aa': 1}}
                for a: str, b: dict[str, int] in l.[dict__str_dict__str_int]items!():
                    x: str = a
                    y: dict[str, int] = b
                    for d: str in b.[dict__str_int]keys():
                        key: str = d
                    for c: int in b.[dict__str_int]values():
                        value: int = c
            """
        )


class TestAnalyzeConditionals(BaseTestCase):

    def test_basic_conditionals(self):
        self.a(
            """
            def main():
                a = 9
                if a == 9:
                    print('a is 9')
                elif a:
                    print('a has value')
                else:
                    print('no value')
            """,
            """
            def main():
                a: int = 9
                if a.[int]__eq__!(9):
                    print('a is 9')
                elif a.[int]__bool__!():
                    print('a has value')
                else:
                    print('no value')
            """
        )

