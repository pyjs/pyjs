from pyjs.testing.helpers import at


def test_open_database_keeps_arguments_outside_generated_callback_scope():
    at(
        """
        from pyjs.web.indexeddb import open_database

        async def main(request: str, resolve: int, upgrade: callable):
            database = await open_database(request, resolve, upgrade)
            database.close()
        """,
        """
        def open_database(name: str, version: int, upgrade: callable | None=None) -> Promise[IDBDatabase]:
            return Promise__IDBDatabase(lambda resolve, reject: _start_open(name, version, upgrade, resolve, reject))

        async def main(request: str, resolve: int, upgrade: callable) -> None:
            database: IDBDatabase = await open_database(request, resolve, upgrade)
            database.[IDBDatabase]close()
        """,
        """
        import { open_database } from './pyjs.web.indexeddb.js';

        export async function main(request, resolve, upgrade) {
            var database = await open_database(request, resolve, {upgrade: upgrade});
            database.close();
        }
        """,
    )


def test_typed_store_preserves_request_results_without_runtime_wrappers():
    at(
        """
        from pyjs.web.indexeddb import IDBObjectStore, TypedIDBStore

        async def main(store: IDBObjectStore):
            notes = TypedIDBStore[str](store)
            value = await notes.get("one").value()
            values = await notes.getAll().value()
            print(value + "!" if value is not None else "missing")
            print(values[0] + "!")
            await notes.clear().value()
        """,
        """
        async def main(store: IDBObjectStore) -> None:
            notes: TypedIDBStore[str] = TypedIDBStore__str(store)
            value: str | None = await notes.[TypedIDBStore__str]get!('one').[IDBRequest__strUNoneType]value!()
            values: list[str] = await notes.[TypedIDBStore__str]getAll!().[IDBRequest__list__str]value!()
            print(value.[str]__add__!('!') if value.[object]__is_not__!(None) else 'missing')
            print($get_list_item(values, 0).[str]__add__!('!'))
            await notes.[TypedIDBStore__str]clear!().[IDBRequest__NoneType]value!()
        """,
        """
        import { request_result as $request_result } from './pyjs.web.indexeddb.js';
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export async function main(store) {
            var notes = store;
            var value = await $request_result(notes.get('one'), {validator: null});
            var values = await $request_result(notes.getAll(), {validator: null});
            console.log((value != null ? value + '!' : 'missing'));
            console.log($get_list_item(values, 0) + '!');
            await $request_result(notes.clear(), {validator: null});
        }
        """,
    )


def test_typed_request_can_validate_data_before_resolving():
    at(
        """
        from pyjs.web.indexeddb import IDBObjectStore, TypedIDBStore

        @js
        def require_text(value: object) -> str:
            if not isinstance(value, str):
                raise ValueError("expected text")
            return value

        async def main(store: IDBObjectStore):
            notes = TypedIDBStore[str](store)
            value = await notes.get("one").value(require_text)
            if value is not None:
                print(value + "!")
        """,
        """
        def require_text(value: object) -> str:
            if not isinstance(value, str):
                raise ValueError('expected text')
            return value

        async def main(store: IDBObjectStore) -> None:
            notes: TypedIDBStore[str] = TypedIDBStore__str(store)
            value: str | None = await notes.[TypedIDBStore__str]get!('one').[IDBRequest__strUNoneType]value!(require_text)
            if value.[object]__is_not__!(None):
                print(value.[str]__add__!('!'))
        """,
        """
        import { request_result as $request_result } from './pyjs.web.indexeddb.js';

        export function require_text(value) {
            if (!((typeof value === 'string'))) {
                throw new RangeError('expected text');
            }
            return value;
        }

        export async function main(store) {
            var notes = store;
            var value = await $request_result(notes.get('one'), {validator: require_text});
            if (value != null) {
                console.log(value + '!');
            }
        }
        """,
    )


def test_request_result_preserves_indexeddb_operation_result_types():
    at(
        """
        from pyjs.web.indexeddb import IDBFactory, IDBObjectStore, request_result

        async def main(factory: IDBFactory, store: IDBObjectStore):
            cleared = await request_result(store.clear())
            count = await request_result(store.count())
            await request_result(store.delete("one"))
            await request_result(factory.deleteDatabase("notes"))
        """,
        """
        def request_result(request: IDBRequest__T, validator: Callable[[T], T] | None=None) -> Promise[T]:
            return Promise__T(lambda resolve, reject: _listen_request(request, validator, resolve, reject))

        async def main(factory: IDBFactory, store: IDBObjectStore) -> None:
            cleared: None = await request_result(store.[IDBObjectStore]clear())
            count: int = await request_result(store.[IDBObjectStore]count())
            await request_result(store.[IDBObjectStore]delete('one'))
            await request_result(factory.[IDBFactory]deleteDatabase('notes'))
        """,
        """
        import { request_result } from './pyjs.web.indexeddb.js';

        export async function main(factory, store) {
            var cleared = await request_result(store.clear());
            var count = await request_result(store.count());
            await request_result(store.delete('one'));
            await request_result(factory.deleteDatabase('notes'));
        }
        """,
    )
