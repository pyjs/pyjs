from .helpers import assert_semantics


def test_client_results_reconstruct_nested_annotated_values():
    assert_semantics(
        r'''
        from pydantic import BaseModel

        from pyjs import js
        from pyjs.javascript import Date
        from pyjs.server import (
            API,
            ClientTransport,
            TransportResponse,
            query,
        )


        @js
        class Item(BaseModel):
            id: int
            label: str


        @js
        class MemoryTransport(ClientTransport):
            async def request(
                self,
                url: str,
                body: str,
                timeout_ms: int = 0,
            ) -> TransportResponse:
                if url.endswith("/missing"):
                    return TransportResponse(200, "null")
                if url.endswith("/containers"):
                    return TransportResponse(
                        200,
                        '[[2,"three"],"2026-08-20T12:34:56.000Z"]',
                    )
                return TransportResponse(
                    200,
                    '{"1":[{"id":7,"label":"Nested"}]}',
                )


        @js
        class ExampleAPI(API):
            @query
            async def grouped(self) -> dict[int, list[Item]] | None:
                return {1: [Item(id=7, label="Nested")]}

            @query
            async def missing(self) -> Item | None:
                return None

            @query
            async def containers(self) -> tuple[set[int | str], Date]:
                return (
                    {2, "three"},
                    Date("2026-08-20T12:34:56.000Z"),
                )


        async def main():
            api = ExampleAPI(transport=MemoryTransport())
            result = await api.grouped()
            if result is not None:
                item = result[1][0]
                print(item.id, item.label)
            print(await api.missing() is None)
            containers = await api.containers()
            print("three" in containers[0], containers[1].toISOString())


        if __name__ == "__main__":
            import asyncio

            asyncio.run(main())
        '''
    )
