from typing import Self

from pyjs import js


@js
class AtomicBatch:
    def __init__(self, api: object):
        self.api = api
        self.operations: list[object] = []
        self.decoders: list[callable] = []
        self.consumed = False

    @js
    def add(self, remote_operation: callable, *values: object) -> Self:
        raise RuntimeError("Atomic batches execute in a transpiled client.")

    @js
    async def commit(self) -> list[object]:
        raise RuntimeError("Atomic batches execute in a transpiled client.")


AtomicBatch.add.source(
    """
    if (this.consumed) {
        throw new Error('Cannot add operations after commit() has been called');
    }
    const names = remote_operation.$arguments;
    if (names === undefined || remote_operation.$operation === undefined) {
        throw new TypeError('AtomicBatch.add() requires a remote API operation');
    }
    if (values.length !== names.length) {
        throw new TypeError(
            `Expected ${names.length} operation arguments, got ${values.length}`
        );
    }
    const payload = Object.fromEntries(
        names.map((name, index) => [name, values[index]])
    );
    const prefix = this.api._path + '/';
    if (!remote_operation.$operation.startsWith(prefix)) {
        throw new TypeError('Atomic operations must belong to the same API');
    }
    const operation = remote_operation.$operation
        .slice(prefix.length)
        .replaceAll('/', '.');
    this.operations.push({
        operation,
        arguments: payload,
    });
    this.decoders.push(remote_operation.$decode);
    return this;
    """
)

AtomicBatch.commit.source(
    """
    if (this.consumed) {
        throw new Error('AtomicBatch.commit() can only be called once');
    }
    this.consumed = true;
    try {
        const results = JSON.parse(await this.api._request(
            'atomic', {operations: this.operations}
        ));
        return results.map((value, index) => this.decoders[index](value));
    } finally {
        this.operations = [];
        this.decoders = [];
    }
    """
)
