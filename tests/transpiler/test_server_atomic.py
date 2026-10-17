import textwrap

from pyjs.javascript.source import compile_source
from pyjs.tooling.node import Node


def test_atomic_batches_are_consumed_by_the_first_commit_attempt():
    source = textwrap.dedent(
        r'''
        from pyjs import js
        from pyjs.server import (
            API,
            ClientTransport,
            OperationError,
            TransportResponse,
            mutation,
        )

        @js
        class MemoryTransport(ClientTransport):
            def __init__(self, fail: bool = False):
                super().__init__()
                self.fail = fail
                self.requests = 0

            async def request(
                self,
                url: str,
                body: str,
                timeout_ms: int = 0,
            ) -> TransportResponse:
                self.requests += 1
                if self.fail:
                    return TransportResponse(
                        422,
                        '{"errors":[{"status":"422","title":"Invalid",'
                        '"detail":"Nope"}]}',
                    )
                return TransportResponse(200, '[7]')

        @js
        class ExampleAPI(API):
            @mutation
            async def set_value(self, value: int) -> int:
                return value

        async def main():
            transport = MemoryTransport()
            api = ExampleAPI(transport=transport)
            batch = api.atomic().add(api.set_value, 7)
            results = await batch.commit()
            print(
                results[0],
                transport.requests,
                len(batch.operations),
                len(batch.decoders),
            )

            add_rejected = False
            commit_rejected = False
            try:
                batch.add(api.set_value, 8)
            except Exception:
                add_rejected = True
            try:
                await batch.commit()
            except Exception:
                commit_rejected = True
            print(add_rejected, commit_rejected)

            failing_transport = MemoryTransport(True)
            failing_api = ExampleAPI(transport=failing_transport)
            failing_batch = failing_api.atomic().add(failing_api.set_value, 9)
            operation_rejected = False
            retry_rejected = False
            try:
                await failing_batch.commit()
            except OperationError:
                operation_rejected = True
            try:
                await failing_batch.commit()
            except Exception:
                retry_rejected = True
            print(
                operation_rejected,
                retry_rejected,
                failing_transport.requests,
                len(failing_batch.operations),
                len(failing_batch.decoders),
            )
        '''
    )
    with compile_source(source) as compilation:
        javascript = compilation.javascript + """\
Promise.resolve(__pyjsEntry__.main()).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""

    result = Node().run_javascript(javascript)

    assert result.returncode == 0
    assert result.stdout == "7 1 0 0\nTrue True\nTrue True 1 0 0\n"
    assert result.stderr == ""
