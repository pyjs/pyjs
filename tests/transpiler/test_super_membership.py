from textwrap import dedent, indent

import pytest

from pyjs.analysis.diagnostics import CompilationError, DiagnosticCode
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import analyze_module_source
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.semantics.helpers import assert_semantics, run_python


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
@pytest.mark.parametrize("operator", ["in", "not in"])
@pytest.mark.parametrize("static", [False, True])
@pytest.mark.parametrize("comparison", ['"k" {operator} super()',
                                        '"k" {operator} super() is not None',
                                        '"k" == "k" {operator} super()'])
def test_implicit_super_membership_has_a_located_diagnostic(environment, operator, static, comparison):
    method = '''
        @staticmethod
        @js.inline(call=contains)
        def __contains__(item: str) -> bool:
            return contains(item)
    ''' if static else '''
        def __contains__(self, item: str) -> bool:
            return contains(item)
    '''
    source = f'''
from pyjs import js
@js
def contains(item: str) -> bool:
    return item == "k"
@js
class Base:
{indent(dedent(method), '    ')}
@js
class Child(Base):
    def check(self) -> bool:
        return {comparison.format(operator=operator)}
def main(flag: bool) -> bool:
    if flag:
        return Child().check()
    return False
'''
    expected = run_python(source + '''
print(main(False))
try:
    main(True)
except TypeError:
    print("invalid super membership")
''')
    assert expected.returncode == 0 and expected.stderr == ""
    assert expected.stdout == "False\ninvalid super membership\n"
    with pytest.raises(CompilationError) as caught:
        with analyze_module_source(source, environment=environment):
            pass
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == DiagnosticCode.UNSUPPORTED_SYNTAX
    assert diagnostic.message == "Membership on super() is not supported"
    assert diagnostic.primary.span.source.text[
        diagnostic.primary.span.start:diagnostic.primary.span.end
    ] == "super()"


@pytest.mark.parametrize("operator", ["in", "not in"])
@pytest.mark.parametrize("comparison", ['"k" {operator} super()',
                                        '"k" {operator} super() is not None',
                                        '"k" == "k" {operator} super()'])
def test_membership_on_a_function_named_super_remains_ordinary(operator, comparison):
    assert_semantics(f'''
        from pyjs import js
        @js
        def super() -> list[str]:
            print("container")
            return ["k"]
        def main() -> None:
            print({comparison.format(operator=operator)})
        main()
    ''')
