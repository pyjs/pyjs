import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python


@pytest.mark.parametrize("parent", ["Exception", "Parent"])
def test_exception_formatter_aliases_keep_lexical_parent_dispatch(tmp_path, parent):
    assert_text_matches_python(f'''
class Parent(Exception):
    def __str__(self) -> str:
        return "parent:" + super().__str__()

class Failure({parent}):
    def __str__(self) -> str:
        base = super()
        alias = base
        return "custom:" + alias.__str__()

def main() -> str:
    return str(Failure("raw"))
''', tmp_path)


def test_super_aliases_follow_copies_branches_and_loop_backedges(tmp_path):
    assert_text_matches_python('''
class Parent:
    def label(self) -> str:
        return "parent"

class Child(Parent):
    def label(self) -> str:
        return "child"

    def read(self, flag: bool) -> str:
        base = super()
        alias = base
        if flag:
            selected = alias
        else:
            selected = super()
        for index in range(2):
            alias = selected
        chosen = alias if flag else super()
        return chosen.label() + ":" + self.label()

def main() -> str:
    return Child().read(True) + "|" + Child().read(False)
''', tmp_path)


@pytest.mark.parametrize("body, diagnostic, line", [
    ("proxy = super()\n        proxy = self\n        return proxy.label()",
     "cannot mix super() proxies and ordinary values in one local", 4),
    ("proxy = super() if flag else self\n        return proxy.label()",
     "cannot mix super() proxies and ordinary values in one local", 3),
    ("return forward(super())", "super() proxies support local aliases and attribute lookup, not escape", 3),
    ("proxy = super()\n        callback = lambda: proxy.label()\n        return callback()",
     "super() proxies cannot escape into closures", 4),
    ("proxy = super()\n        for proxy in [self]:\n            pass\n        return proxy.label()",
     "cannot mix super() proxies and other local bindings", 4),
])
def test_ambiguous_or_escaping_super_aliases_have_located_diagnostics(body, diagnostic, line):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f'''
class Parent:
    def label(self) -> str:
        return "parent"
class Child(Parent):
    def label(self) -> str:
        return "child"
    def read(self, flag: bool) -> str:
        {body}
def forward(value: Parent) -> str:
    return value.label()
def main() -> str:
    return Child().read(True)
''')
    assert str(caught.value) == f"JVM {diagnostic} at line {line}"
