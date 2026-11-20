from pyjs.testing.helpers import at


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
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export async function main(store) {
            var notes = store;
            var value = await ((getRequest) => new Promise((resolve, reject) => {const request = getRequest();request.addEventListener('success', () => resolve(request.result), {once: true});request.addEventListener('error', () => reject(request.error), {once: true});}))(() => (notes.get('one')));
            var values = await ((getRequest) => new Promise((resolve, reject) => {const request = getRequest();request.addEventListener('success', () => resolve(request.result), {once: true});request.addEventListener('error', () => reject(request.error), {once: true});}))(() => (notes.getAll()));
            console.log((value != null ? value + '!' : 'missing'));
            console.log($get_list_item(values, 0) + '!');
            await ((getRequest) => new Promise((resolve, reject) => {const request = getRequest();request.addEventListener('success', () => resolve(request.result), {once: true});request.addEventListener('error', () => reject(request.error), {once: true});}))(() => (notes.clear()));
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
        export function require_text(value) {
            if (!((typeof value === 'string'))) {
                throw new RangeError('expected text');
            }
            return value;
        }

        export async function main(store) {
            var notes = store;
            var value = await ((getRequest, getValidator) => new Promise((resolve, reject) => {const request = getRequest();const validate = getValidator();request.addEventListener('success', () => {try{resolve(validate(request.result))}catch(error){reject(error)}}, {once: true});request.addEventListener('error', () => reject(request.error), {once: true});}))(() => (notes.get('one')), () => (require_text));
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
        async def main(factory: IDBFactory, store: IDBObjectStore) -> None:
            cleared: None = await request_result(store.[IDBObjectStore]clear())
            count: int = await request_result(store.[IDBObjectStore]count())
            await request_result(store.[IDBObjectStore]delete('one'))
            await request_result(factory.[IDBFactory]deleteDatabase('notes'))
        """,
        """
        export async function main(factory, store) {
            var cleared = await ((getRequest) => new Promise((resolve, reject) => {const request = getRequest();request.addEventListener('success', () => resolve(request.result), {once: true});request.addEventListener('error', () => reject(request.error), {once: true});}))(() => (store.clear()));
            var count = await ((getRequest) => new Promise((resolve, reject) => {const request = getRequest();request.addEventListener('success', () => resolve(request.result), {once: true});request.addEventListener('error', () => reject(request.error), {once: true});}))(() => (store.count()));
            await ((getRequest) => new Promise((resolve, reject) => {const request = getRequest();request.addEventListener('success', () => resolve(request.result), {once: true});request.addEventListener('error', () => reject(request.error), {once: true});}))(() => (store.delete('one')));
            await ((getRequest) => new Promise((resolve, reject) => {const request = getRequest();request.addEventListener('success', () => resolve(request.result), {once: true});request.addEventListener('error', () => reject(request.error), {once: true});}))(() => (factory.deleteDatabase('notes')));
        }
        """,
    )
