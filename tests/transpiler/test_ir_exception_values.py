from textwrap import dedent

from pyjs.analysis.ir import ExceptionRaise, build_program_ir, validate_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT


def test_exception_lowering_retains_formatting_dependencies_and_payload_lifetimes():
    with analyze_source('''
        class Payload:
            def __str__(self) -> str:
                return "payload"
        def fail(value: Payload) -> None:
            raise StopIteration(value)
        def main() -> None:
            fail(Payload())
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            class Payload:

                def __str__() -> str:
                    block entry:
                        return 'payload'

            def fail(value: Payload) -> None:
                block entry:
                    raise StopIteration(value)

            def main() -> None:
                block entry:
                    fail(new[external] Payload())
                    return None
        ''').rstrip()
        function = analysis.entry_point.container.search("fail")
        assert function.ir.lifetime.external_parameters == frozenset({"value"})
        raised = next(node for block in function.ir.blocks for node in block.body if isinstance(node, ExceptionRaise))
        assert [(method.cls.name, method.name) for method in raised.runtime_methods] == [("Payload", "__str__")]
        assert [(receiver.name, names) for receiver, names in raised.runtime_protocols] == [("Payload", ("__str__",))]
        validate_program_ir(build_program_ir(analysis.entry_point))
