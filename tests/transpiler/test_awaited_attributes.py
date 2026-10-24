from pyjs.testing.helpers import at


def test_awaited_object_is_an_instance_for_field_access():
    at(
        '''
        @js
        class Value:
            def __init__(self, count: int):
                self.count = count

        @js
        async def value() -> Value:
            return Value(3)

        async def main() -> int:
            return (await value()).count
        ''',
        '''
        class Value:

            def __init__(count: int) -> None:
                self.count = count

        async def value() -> Value:
            return Value(3)

        async def main() -> int:
            return (await value()).count
        ''',
        '''
        export class Value {

            constructor(count) {
                this.count = count;
            }
        }

        export async function value() {
            return new Value(3);
        }

        export async function main() {
            return (await value()).count;
        }
        ''',
    )
