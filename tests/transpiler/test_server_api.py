import sys
import textwrap

from pyjs.analysis.source import create_module
from pyjs.javascript.source import compile_source
from pyjs.testing.helpers import (
    assert_compilation_diagnostic,
    assert_compiled_sources,
    assert_transpile,
)
from pyjs.tooling.node import Node


def test_native_host_method_acquires_iterable_at_call_boundary():
    assert_transpile('''
        from collections.abc import Iterable
        from pyjs.web.serviceworker import Cache
        async def main(cache: Cache, values: Iterable[str]):
            await cache.addAll(values)
    ''', '''
        export async function main(cache, values) {
            await cache.addAll(((value)=>value==null?value:value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)(values));
        }
    ''')


def test_native_host_starred_arguments_adapt_bound_items_not_the_pack():
    assert_transpile('''
        from collections.abc import Iterable
        @js.native
        class Set:
            def __init__(self, values: Iterable[str] | None = None): ...
        def main(values: tuple[dict[str, int]]):
            Set(*values)
    ''', '''
        export function main(values) {
            new Set(...(($args)=>{if($args.length>0)$args[0]=((value)=>value==null?value:value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)($args[0]);return $args;})([...values]));
        }
    ''')


def test_builtin_mapping_views_are_not_dynamically_acquired_twice():
    assert_transpile('''
        from typing import TypedDict
        class Row(TypedDict):
            a: int
        def main(mapping: dict[str, int], row: Row):
            for key in mapping: pass
            for value in mapping.values(): pass
            for pair in mapping.items(): pass
            for key in row.keys(): pass
            for value in row.values(): pass
            for pair in row.items(): pass
            return [key for key in mapping.keys()]
    ''', '''
        export function main(mapping, row) {
            for (var key of mapping.keys()) {
            }
            for (var value of mapping.values()) {
            }
            for (var pair of mapping.entries()) {
            }
            for (var key of Object.keys(row)) {
            }
            for (var value of Object.values(row)) {
            }
            for (var pair of Object.entries(row)) {
            }
            return Array.from(mapping.keys()).map(key => key);
        }
    ''')


def test_watched_query_emits_reached_generic_specialization():
    assert_compiled_sources(
        """
        from pyjs import js
        from pyjs.server import WatchedQuery

        @js
        async def load(value: int) -> int:
            return value

        @js
        async def load_text() -> str:
            return "unused"

        @js
        async def unused():
            query = WatchedQuery[str](load_text)
            await query.get()

        async def main():
            query = WatchedQuery(load, 3)
            value = await query.get()
            query.set_args(4)
            value = await query.reload()
        """,
        {
            "pyjs.server.watch": """
                export class WatchedQuery__int {

                    constructor(loader, ...args) {
                        this.current = null;
                        this.loaded = false;
                        this.loading = false;
                        this.error = null;
                        this.stale = true;
                        this._loader = loader;
                        this.operation_path = loader.$operation ?? null;
                        this.argument_names = loader.$arguments ?? [];
                        this.arguments = [];
                        for (var argument of args) {
                            (this.arguments.push(argument), null);
                        }
                        this._update = null;
                        this._pending = null;
                        this._generation = 0;
                        this._subscription_changed = null;
                    }

                    async refresh() {
                        if (this._pending != null) {
                            return (await this._pending);
                        }
                        this.loading = true;
                        this.error = null;
                        var generation = this._generation;
                        this._pending = this._loader(...this.arguments);
                        try {
                            var value = (await this._pending);
                            this.current = value;
                            this.loaded = true;
                            this.stale = generation != this._generation;
                            if (!this.stale && this._update != null) {
                                this._update(value);
                            }
                            return value;
                        } catch (error) {
                            this.error = error;
                            throw error;
                        } finally {
                            this.loading = false;
                            this._pending = null;
                        }
                    }

                    async get() {
                        if (!this.stale && this.loaded) {
                            return this.current;
                        }
                        return await this.refresh();
                    }

                    async reload() {
                        this.invalidate();
                        var value = await this.refresh();
                        while (this.stale) {
                            value = await this.refresh();
                        }
                        return value;
                    }

                    invalidate() {
                        var $assignment2 = this;
                        $assignment2._generation = $assignment2._generation + 1;
                        this.stale = true;
                    }

                    set_args(...args) {
                        (this.arguments.length = 0, null);
                        for (var argument of args) {
                            (this.arguments.push(argument), null);
                        }
                        this.invalidate();
                        if (this._subscription_changed != null) {
                            this._subscription_changed();
                        }
                        return this;
                    }
                }
            """,
            "_pyjs_source_": """
                import { WatchedQuery__int } from './pyjs.server.watch.js';

                export async function load(value) {
                    return value;
                }

                export async function main() {
                    var query = new WatchedQuery__int(load, 3);
                    var value = await query.get();
                    query.set_args(4);
                    value = await query.reload();
                }
            """,
        },
    )


def test_live_session_emits_topic_routing_and_transport_fallback():
    assert_compiled_sources(
        """
        from pyjs import js
        from pyjs.server import LiveSession, WatchedQuery

        @js
        async def load() -> int:
            return 1

        @js
        def updated(value: int):
            pass

        async def main():
            session = LiveSession(autostart=False)
            query = WatchedQuery[int](load).on_update(updated).watch(
                session,
                "issues",
            )
            session.start()
            session.close()
        """,
        {
            "pyjs.server.watch": """
                import { ClientTransport, FetchTransport } from './pyjs.server.transport.js';
                import { contains_equal_sequence_item as $contains_equal_sequence_item, get_list_item as $get_list_item, set_list_item as $set_list_item } from './pyjs.python.js';

                export class WatchedQuery__int {

                    constructor(loader, ...args) {
                        this.current = null;
                        this.loaded = false;
                        this.loading = false;
                        this.error = null;
                        this.stale = true;
                        this._loader = loader;
                        this.operation_path = loader.$operation ?? null;
                        this.argument_names = loader.$arguments ?? [];
                        this.arguments = [];
                        for (var argument of args) {
                            (this.arguments.push(argument), null);
                        }
                        this._update = null;
                        this._pending = null;
                        this._generation = 0;
                        this._subscription_changed = null;
                    }

                    async refresh() {
                        if (this._pending != null) {
                            return (await this._pending);
                        }
                        this.loading = true;
                        this.error = null;
                        var generation = this._generation;
                        this._pending = this._loader(...this.arguments);
                        try {
                            var value = (await this._pending);
                            this.current = value;
                            this.loaded = true;
                            this.stale = generation != this._generation;
                            if (!this.stale && this._update != null) {
                                this._update(value);
                            }
                            return value;
                        } catch (error) {
                            this.error = error;
                            throw error;
                        } finally {
                            this.loading = false;
                            this._pending = null;
                        }
                    }

                    invalidate() {
                        var $assignment2 = this;
                        $assignment2._generation = $assignment2._generation + 1;
                        this.stale = true;
                    }

                    on_update(callback) {
                        this._update = callback;
                        return this;
                    }

                    async _refresh_current() {
                        try {
                            while (this.stale) {
                                await this.refresh();
                            }
                        } catch (_error) {
                        }
                    }

                    _refresh_live() {
                        this._refresh_current.bind(this)().catch(() => {});
                    }

                    _live_request(identifier, session_path) {
                        if (this.operation_path == null) {
                            return null;
                        }
                        var prefix = session_path + '/';
                        if (!(this.operation_path.startsWith(prefix))) {
                            return null;
                        }
                        var operation = this.operation_path.slice(session_path.length + 1).replaceAll('/', '.');
                        return ({arguments: Object.fromEntries(this.argument_names.map((name, index) => [name, this.arguments[index]])), generation: this._generation, id: identifier, operation: operation});
                    }

                    _accept_live(generation, value) {
                        if (generation != this._generation || this._pending != null) {
                            return false;
                        }
                        this.current = this._loader.$decode ? this._loader.$decode(value) : value;
                        this.loaded = true;
                        this.loading = false;
                        this.error = null;
                        this.stale = false;
                        if (this._update != null) {
                            this._update(this.current);
                        }
                        return true;
                    }

                    watch(session, ...topics) {
                        var selected = [];
                        for (var topic of topics) {
                            (selected.push(topic), null);
                        }
                        if (!(selected.length)) {
                            if (this.operation_path != null) {
                                var prefix = session.path + '/';
                                if (this.operation_path.startsWith(prefix)) {
                                    var operation = this.operation_path.slice(session.path.length + 1).replaceAll('/', '.');
                                    var inferred_topic = ((operation) => { const separator = operation.lastIndexOf('.'); return separator < 0 ? null : operation.slice(0, separator); })(operation);
                                    if (inferred_topic != null) {
                                        (selected.push(inferred_topic), null);
                                    }
                                }
                            }
                            if (!(selected.length)) {
                                (selected.push('*'), null);
                            }
                        }
                        this._subscription_changed = session._subscriptions_changed.bind(session);
                        session._add(this.invalidate.bind(this), this._refresh_live.bind(this), this._live_request.bind(this), this._accept_live.bind(this), selected);
                        return this;
                    }
                }

                export class _LiveWatch {

                    constructor(invalidate, refresh, request, accept, topics) {
                        this.id = 0;
                        this._invalidate = invalidate;
                        this._refresh = refresh;
                        this._request = request;
                        this._accept = accept;
                        this.topics = topics;
                    }

                    matches(topics) {
                        if ($contains_equal_sequence_item(topics, '*') || $contains_equal_sequence_item(this.topics, '*')) {
                            return true;
                        }
                        for (var topic of topics) {
                            if ((($compare_left0, $compare_right1) => $contains_equal_sequence_item($compare_right1, $compare_left0))(topic, this.topics)) {
                                return true;
                            }
                        }
                        return false;
                    }

                    mark_stale() {
                        this._invalidate();
                    }

                    request(session_path) {
                        return this._request(this.id, session_path);
                    }

                    subscription_request(session_path) {
                        var request = this.request(session_path);
                        if (request == null) {
                            return null;
                        }
                        return ({arguments: request['arguments'], generation: request['generation'], id: request['id'], operation: request['operation'], topics: this.topics});
                    }

                    refresh() {
                        this._refresh();
                    }

                    accept(result) {
                        return this._accept(result['generation'], result['value']);
                    }
                }

                export class LiveSession {

                    constructor({ path='/api', transport=null, autostart=true} = {}) {
                        this.path = path;
                        if (path.endsWith('/')) {
                            this.path = [...path].slice(0,-1).join('');
                        }
                        this.autostart = autostart;
                        this._transport = transport == null ? new FetchTransport() : transport;
                        this.transport = 'stopped';
                        this.sequence = 0;
                        this._source = null;
                        this._watches = [];
                        this._next_watch_id = 1;
                        this._result_queries = [];
                        this._result_refreshing = false;
                        this._subscription = '';
                        this._subscription_version = 0;
                        this._subscription_syncing = false;
                        this._closed = false;
                    }

                    _add(invalidate, refresh, request, accept, topics) {
                        var watch = new _LiveWatch(invalidate, refresh, request, accept, topics);
                        watch.id = this._next_watch_id;
                        var $assignment8 = this;
                        $assignment8._next_watch_id = $assignment8._next_watch_id + 1;
                        (this._watches.push(watch), null);
                        if (!this.autostart) {
                            return;
                        }
                        if (watch.subscription_request(this.path) != null) {
                            this._subscriptions_changed();
                        } else if (this.transport === 'stopped') {
                            this.start();
                        }
                    }

                    start() {
                        if (this.transport !== 'stopped') {
                            return;
                        }
                        this._closed = false;
                        if (this._subscription_queries().length) {
                            this._start_subscription_sync();
                            return;
                        }
                        this._open_source('');
                    }

                    _open_source(subscription) {
                        var path = this.path + '/_live/events';
                        if (subscription) {
                            path = path + ('?subscription=' + encodeURIComponent(subscription));
                        }
                        var source = new EventSource(path);
                        source.addEventListener('invalidate', this._receive_event.bind(this));
                        source.addEventListener('result', this._receive_event.bind(this));
                        source.addEventListener('resync', this._receive_event.bind(this));
                        source.addEventListener('error', this._sse_failed.bind(this));
                        this._source = source;
                        this.transport = 'sse';
                    }

                    close() {
                        this._closed = true;
                        (this._result_queries.length = 0, null);
                        if (this._source != null) {
                            this._source.close();
                            this._source = null;
                        }
                        this.transport = 'stopped';
                    }

                    _subscription_queries() {
                        var queries = [];
                        for (var watch of this._watches) {
                            var request = watch.subscription_request(this.path);
                            if (request != null) {
                                (queries.push(request), null);
                            }
                        }
                        return queries;
                    }

                    _subscriptions_changed() {
                        var $assignment2 = this;
                        $assignment2._subscription_version = $assignment2._subscription_version + 1;
                        if (this.autostart) {
                            this._start_subscription_sync();
                        }
                    }

                    _start_subscription_sync() {
                        if (this._subscription_syncing) {
                            return;
                        }
                        this._subscription_syncing = true;
                        this._sync_subscriptions.bind(this)().catch(() => {});
                    }

                    async _sync_subscriptions() {
                        try {
                            await new Promise((resolve) => setTimeout(resolve, 0));
                            while (!this._closed) {
                                var version = this._subscription_version;
                                var queries = this._subscription_queries();
                                if (!(queries.length)) {
                                    if (this.transport === 'stopped') {
                                        this._open_source('');
                                    }
                                    return;
                                }
                                var request = ({queries: queries, subscription: this._subscription});
                                try {
                                    var response = await this._transport.request(this.path + '/_live/subscribe', JSON.stringify(request));
                                    if (!response.ok) {
                                        throw new RangeError('Live subscription failed.');
                                    }
                                    var message = JSON.parse(response.body);
                                    if (this._closed) {
                                        return;
                                    }
                                    var subscription = message['subscription'];
                                } catch (_error) {
                                    if (!this._closed && this.transport === 'stopped') {
                                        this._open_source('');
                                    }
                                    return;
                                }
                                if (version != this._subscription_version) {
                                    continue
                                }
                                var changed = subscription !== this._subscription;
                                this._subscription = subscription;
                                if (changed && this._source != null) {
                                    this._source.close();
                                    this._source = null;
                                    this.transport = 'stopped';
                                }
                                if (this.transport === 'stopped') {
                                    this._open_source(subscription);
                                }
                                return;
                            }
                        } finally {
                            this._subscription_syncing = false;
                        }
                    }

                    _receive_event(event) {
                        if (!((event instanceof MessageEvent))) {
                            return;
                        }
                        var data = event.data;
                        if (!((typeof data === 'string'))) {
                            return;
                        }
                        this._receive(JSON.parse(data));
                    }

                    _receive(message) {
                        if (this._closed) {
                            return;
                        }
                        var sequence = message['sequence'];
                        if (message['type'] !== 'resync' && sequence <= this.sequence) {
                            return;
                        }
                        this.sequence = sequence;
                        var topics = message['topics'];
                        var results = [];
                        if (message['type'] === 'result') {
                            results = message['results'];
                        }
                        for (var watch of this._watches) {
                            if (!watch.matches(topics)) {
                                continue
                            }
                            var accepted = false;
                            for (var result of results) {
                                if (result['id'] == watch.id) {
                                    accepted = watch.accept(result);
                                    break
                                }
                            }
                            if (accepted) {
                                continue
                            }
                            watch.mark_stale();
                            var request = watch.request(this.path);
                            if (request == null) {
                                watch.refresh();
                            } else {
                                this._queue_result(request);
                            }
                        }
                        this._start_results();
                    }

                    _queue_result(query) {
                        var index = 0;
                        while (index < this._result_queries.length) {
                            var pending = $get_list_item(this._result_queries, index);
                            if (pending['id'] == query['id']) {
                                var $assignment4 = query;
                                $set_list_item(this._result_queries, index, $assignment4);
                                return;
                            }
                            index = index + 1;
                        }
                        (this._result_queries.push(query), null);
                    }

                    _start_results() {
                        if (this._result_refreshing || !(this._result_queries.length)) {
                            return;
                        }
                        this._result_refreshing = true;
                        this._drain_results.bind(this)().catch(() => {});
                    }

                    async _drain_results() {
                        try {
                            while (this._result_queries.length > 0) {
                                var queries = this._result_queries;
                                this._result_queries = [];
                                await this._refresh_results(queries);
                            }
                        } finally {
                            this._result_refreshing = false;
                        }
                    }

                    _watch(identifier) {
                        for (var watch of this._watches) {
                            if (watch.id == identifier) {
                                return watch;
                            }
                        }
                        return null;
                    }

                    _fallback(queries) {
                        for (var query of queries) {
                            var watch = this._watch(query['id']);
                            if (watch != null) {
                                watch.refresh();
                            }
                        }
                    }

                    async _refresh_results(queries) {
                        var request = ({queries: queries});
                        try {
                            var response = await this._transport.request(this.path + '/_live/refresh', JSON.stringify(request));
                            if (!response.ok) {
                                this._fallback(queries);
                                return;
                            }
                            var message = JSON.parse(response.body);
                            if (this._closed) {
                                return;
                            }
                            for (var result of message['results']) {
                                var watch = this._watch(result['id']);
                                if (watch != null) {
                                    if (!watch.accept(result)) {
                                        watch.refresh();
                                    }
                                }
                            }
                        } catch (_error) {
                            if (!this._closed) {
                                this._fallback(queries);
                            }
                        }
                    }

                    async _sse_failed(event) {
                        if (this.transport !== 'sse') {
                            return;
                        }
                        if (this._source != null) {
                            this._source.close();
                            this._source = null;
                        }
                        this.transport = 'poll';
                        await this._poll();
                    }

                    async _poll() {
                        while (!this._closed && this.transport === 'poll') {
                            try {
                                var response = await fetch(this.path + '/_live/poll?after=' + String(this.sequence));
                                if (response.status == 204) {
                                    continue
                                }
                                if (response.status == 401 || response.status == 403) {
                                    this.close();
                                    return;
                                }
                                if (!response.ok) {
                                    await new Promise((resolve) => setTimeout(resolve, 1000));
                                    continue
                                }
                                this._receive(JSON.parse((await response.text())));
                            } catch (_error) {
                                await new Promise((resolve) => setTimeout(resolve, 1000));
                            }
                        }
                    }
                }
            """,
            "pyjs.server.transport": """
                export class TransportResponse {

                    constructor(status, body) {
                        this.status = status;
                        this.body = body;
                    }

                    get ok() {
                        return this.status >= 200 && this.status < 300;
                    }
                }

                export class ClientTransport {

                    async request(url, body, { timeout_ms=0} = {}) {
                    }
                }

                export class FetchTransport extends ClientTransport {

                    request_headers() {
                        return new Map([['Content-Type', 'application/json']]);
                    }

                    async request(url, body, { timeout_ms=0} = {}) {
                        var options = ({method: 'POST', headers: this.request_headers(), body: body});
                        if (timeout_ms > 0) {
                            var $assignment6 = AbortSignal.timeout(timeout_ms);
                            (options['signal'] = $assignment6, null);
                        }
                        var response = await fetch(url, options);
                        return new TransportResponse(response.status, await response.text());
                    }
                }
            """,
            "_pyjs_source_": """
                import { LiveSession, WatchedQuery__int } from './pyjs.server.watch.js';

                export async function load() {
                    return 1;
                }

                export function updated(value) {
                }

                export async function main() {
                    var session = new LiveSession({autostart: false});
                    var query = new WatchedQuery__int(load).on_update(updated).watch(session, 'issues');
                    session.start();
                    session.close();
                }
            """,
            "pyjs.python": """
                export function equal_value(left, right) {
                    const numeric = value => typeof value === 'number' ||
                        typeof value === 'boolean' || typeof value === 'bigint';
                    if (numeric(left) && numeric(right)) {
                        if (typeof left === 'bigint' || typeof right === 'bigint') {
                            const integer = typeof left === 'bigint' ? right : left;
                            if (typeof integer === 'number' && !Number.isInteger(integer)) return false;
                            return BigInt(left) === BigInt(right);
                        }
                        return Number(left) === Number(right);
                    }
                    if (Array.isArray(left) && Array.isArray(right)) {
                        if (left === right) return true;
                        return left.length === right.length &&
                            left.every((value, index) => value === right[index] || equal_value(value, right[index]));
                    }
                    const plainObject = value => value !== null && typeof value === 'object' &&
                        Object.getPrototypeOf(value) === Object.prototype;
                    if (left === right && (left instanceof Map || plainObject(left))) return true;
                    const mappingEntries = value => value instanceof Map ? [...value] :
                        plainObject(value) ? Object.entries(value) : null;
                    const missing = {};
                    const mappingValue = (mapping, key) => {
                        if (mapping instanceof Map) {
                            return mapping.has(key) ? mapping.get(key) : missing;
                        }
                        return typeof key === 'string' && Object.hasOwn(mapping, key) ?
                            mapping[key] : missing;
                    };
                    const leftEntries = mappingEntries(left);
                    const rightEntries = mappingEntries(right);
                    if (leftEntries !== null && rightEntries !== null) {
                        if (leftEntries.length !== rightEntries.length) return false;
                        for (const [key, value] of leftEntries) {
                            const exact = mappingValue(right, key);
                            if (exact !== missing) {
                                if (value !== exact && !equal_value(value, exact)) return false;
                                continue;
                            }
                            let found = false;
                            for (const [otherKey, otherValue] of rightEntries) {
                                if (key === otherKey || equal_value(key, otherKey)) {
                                    if (value !== otherValue && !equal_value(value, otherValue)) return false;
                                    found = true;
                                    break;
                                }
                            }
                            if (!found) return false;
                        }
                        return true;
                    }
                    if (left instanceof Set && right instanceof Set) {
                        if (left === right) return true;
                        if (left.size !== right.size) return false;
                        for (const value of left) {
                            if (right.has(value)) continue;
                            let found = false;
                            for (const other of right) {
                                if (equal_value(value, other)) {
                                    found = true;
                                    break;
                                }
                            }
                            if (!found) return false;
                        }
                        return true;
                    }
                    if (left !== null && typeof left?.__eq__ === 'function') {
                        return left.__eq__(right);
                    }
                    if (right !== null && typeof right?.__eq__ === 'function') {
                        return right.__eq__(left);
                    }
                    return left === right;
                }

                export function contains_equal_sequence_item(values, item) {
                    for (var value of ((value)=>value instanceof Map?value.keys():Object.getPrototypeOf(value)===Object.prototype?Object.keys(value):value)(values)) {
                        if (value === item || equal_value(value, item)) {
                            return true;
                        }
                    }
                    return false;
                }

                export function get_list_item(target, index) {
                    var actual_index = index < 0 ? index + target.length : index;
                    if (actual_index < 0 || actual_index >= target.length) {
                        throw new IndexError('list index out of range');
                    }
                    return target[Number(actual_index)];
                }

                export function set_list_item(target, index, value) {
                    var actual_index = index < 0 ? index + target.length : index;
                    if (actual_index < 0 || actual_index >= target.length) {
                        throw new IndexError('list assignment index out of range');
                    }
                    (target[Number(actual_index)] = value, null);
                }

                export class LookupError extends Error {
                }

                export class IndexError extends LookupError {
                }
            """,
        },
    )


def test_operation_errors_are_typed_in_client_exception_handlers():
    assert_transpile(
        """
        from pyjs.server import OperationError

        def main(error: Exception):
            try:
                raise error
            except Exception as caught:
                if isinstance(caught, OperationError):
                    detail = caught.issues[0].detail
        """,
        """
        import { OperationError } from './pyjs.server.errors.js';
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export function main(error) {
            try {
                throw error;
            } catch (caught) {
                if ((caught instanceof OperationError)) {
                    var detail = $get_list_item(caught.issues, 0).detail;
                }
            }
        }
        """,
    )


def test_jsonapi_query_decodes_the_generated_resource_document():
    assert_transpile(
        '''
        from pydantic import BaseModel
        from pyjs.server import API, Resource, query

        @js
        class Task(BaseModel):
            id: str
            title: str

        @js
        class TaskResource(Resource[Task]):
            @query
            async def list(self) -> list[Task]:
                raise RuntimeError("server only")

        @js
        class ApplicationAPI(API):
            tasks: TaskResource

        api = ApplicationAPI()

        async def main():
            tasks = await api.tasks.list()
        ''',
        '''
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API, Resource } from './pyjs.server.js';
        import { JSONAPIDecoder as $JSONAPIDecoder } from './pyjs.server.jsonapi.js';

        export class Task extends BaseModel {
        }
        Task.__pyjs_required__ = ['id', 'title'];
        Task.__pyjs_fields__ = new Map([['id', 'str'], ['title', 'str']]);

        export class TaskResource extends Resource {

            async list() {
                const $document = new $JSONAPIDecoder(JSON.parse(await this._request('list', {})), new Map([['tasks', Task]]));
                return $document.data;
            }
        }


        export class ApplicationAPI extends API {
        }
        Object.defineProperty(ApplicationAPI.prototype, 'tasks', {get() { return this.__pyjs_api_tasks ||= new TaskResource({path: this._path + '/tasks', transport: this._transport, timeout_ms: this._timeout_ms}); } });
        export const api = new ApplicationAPI();

        export async function main() {
            var tasks = await api.tasks.list();
        }
        ''',
    )


def test_typed_page_query_decodes_its_generic_model_result():
    assert_transpile(
        '''
        from pydantic import BaseModel
        from pyjs.server import API, CursorPageRequest, Page, Resource, query

        @js
        class Item(BaseModel):
            id: int

        @js
        class Items(Resource[Item]):
            @query
            async def list(self, page: CursorPageRequest) -> Page[Item]:
                raise RuntimeError("server only")

        @js
        class ApplicationAPI(API):
            items: Items

        api = ApplicationAPI()

        async def main():
            page = await api.items.list(CursorPageRequest(size=2))
            print(page.items[0].id)
        ''',
        '''
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API, Resource } from './pyjs.server.js';
        import { CursorPageRequest, Page__Item } from './pyjs.server.pagination.js';
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export class Item extends BaseModel {
        }
        Item.__pyjs_required__ = ['id'];
        Item.__pyjs_fields__ = new Map([['id', 'int']]);
        (globalThis.$pyjsModels ??= new Map()).set('_pyjs_source_.Item', Item);

        export class Items extends Resource {

            async list(page) {
                const $value = JSON.parse(await this._request('list', {page: page}));
                return this._decode_result($value, ["model","pyjs.server.pagination.Page__Item"]);
            }
        }


        export class ApplicationAPI extends API {
        }
        Object.defineProperty(ApplicationAPI.prototype, 'items', {get() { return this.__pyjs_api_items ||= new Items({path: this._path + '/items', transport: this._transport, timeout_ms: this._timeout_ms}); } });
        export const api = new ApplicationAPI();

        export async function main() {
            var page = await api.items.list(new CursorPageRequest({size: 2}));
            console.log($get_list_item(page.items, 0).id);
        }
        ''',
    )


def test_generic_model_dependency_survives_a_circular_bundle_import():
    provider_name = "_pyjs_page_model_provider"
    entry_name = "_pyjs_page_model_entry"
    create_module(
        textwrap.dedent(
            '''
            from pydantic import BaseModel

            from pyjs import js
            from pyjs.server import Page

            @js
            class Item(BaseModel):
                id: int

            @js
            def make_page() -> Page[Item]:
                return Page[Item](items=[Item(id=9)])
            '''
        ),
        filename="page_model_provider.py",
        module_name=provider_name,
    )
    try:
        source = textwrap.dedent(
            f'''
            from pyjs.server import CursorPageRequest
            from {provider_name} import make_page

            def main():
                request = CursorPageRequest(size=1)
                print(make_page().items[0].id + request.size)
            '''
        )
        with compile_source(source, module_name=entry_name) as compilation:
            javascript = compilation.javascript + "\n__pyjsEntry__.main();\n"

        result = Node().run_javascript(javascript)

        assert result.returncode == 0
        assert result.stdout == "10\n"
        assert result.stderr == ""
    finally:
        sys.modules.pop(provider_name, None)
        sys.modules.pop(entry_name, None)


def test_operations_reject_unsupported_client_result_types():
    assert_compilation_diagnostic(
        '''
        from pyjs import js
        from pyjs.server import API, query

        @js
        class Result:
            pass

        @js
        class ExampleAPI(API):
            @query
            async def load(self) -> Result:
                raise RuntimeError

        async def main():
            await ExampleAPI().load()
        ''',
        '''
          File "unsupported_result.py", line 12
            async def load(self) -> Result:
                      ^^^^
        pyjs.CompilationError: Operation 'load' has unsupported client result type 'Result'. [PYJS2004]
        help: Return a supported primitive, Pydantic model, optional, list, dictionary, tuple, set, or Page value.
        ''',
        filename="unsupported_result.py",
    )


def test_stream_client_uses_its_declared_session_without_unneeded_decoding():
    assert_transpile(
        '''
        from pyjs import js
        from pyjs.server import API, Stream, stream

        @js
        class Logs(API):
            @stream
            def output(self) -> Stream[str]:
                raise RuntimeError

        def main():
            Logs().output()
        ''',
        '''
        import { API } from './pyjs.server.js';
        import { StreamSession as $StreamSession } from './pyjs.server.stream_client.js';

        export class Logs extends API {

            output() {
                const $arguments = {};
                const $path = this._path + '/output?arguments=' + encodeURIComponent(JSON.stringify($arguments));
                return new $StreamSession($path, ($value) => $value);
            }
        }


        export function main() {
            new Logs().output();
        }
        ''',
    )


def test_stream_callbacks_must_accept_the_declared_event_type():
    assert_compilation_diagnostic(
        '''
        from pydantic import BaseModel

        from pyjs import js
        from pyjs.server import API, Stream, stream

        @js
        class Line(BaseModel):
            text: str

        @js
        class Logs(API):
            @stream
            def output(self) -> Stream[Line]:
                raise RuntimeError

        @js
        def wrong(value: str) -> None:
            pass

        def main():
            Logs().output().on_event(wrong)
        ''',
        '''
          File "stream_callback.py", line 22
            Logs().output().on_event(wrong)
                                     ^^^^^
        pyjs.CompilationError: Callable argument 'callback' to on_event accepts str, but must accept Line [PYJS1104]
        note: stream_callback.py:18:5: callable defined here
        help: Widen the callable parameter annotation to accept every input value.
        ''',
        filename="stream_callback.py",
    )


def test_generated_client_temporaries_do_not_collide_with_operation_arguments():
    assert_transpile(
        '''
        from pydantic import BaseModel
        from pyjs.server import API, Resource, query

        @js
        class Item(BaseModel):
            id: str

        @js
        class ItemResource(Resource[Item]):
            @query
            async def get(self, document: str) -> Item:
                raise RuntimeError("server only")

        @js
        class ApplicationAPI(API):
            items: ItemResource

        api = ApplicationAPI()

        async def main():
            item = await api.items.get("one")
        ''',
        '''
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API, Resource } from './pyjs.server.js';
        import { JSONAPIDecoder as $JSONAPIDecoder } from './pyjs.server.jsonapi.js';

        export class Item extends BaseModel {
        }
        Item.__pyjs_required__ = ['id'];
        Item.__pyjs_fields__ = new Map([['id', 'str']]);

        export class ItemResource extends Resource {

            async get(document) {
                const $document = new $JSONAPIDecoder(JSON.parse(await this._request('get', {document: document})), new Map([['items', Item]]));
                return $document.data;
            }
        }


        export class ApplicationAPI extends API {
        }
        Object.defineProperty(ApplicationAPI.prototype, 'items', {get() { return this.__pyjs_api_items ||= new ItemResource({path: this._path + '/items', transport: this._transport, timeout_ms: this._timeout_ms}); } });
        export const api = new ApplicationAPI();

        export async function main() {
            var item = await api.items.get('one');
        }
        ''',
    )


def test_jsonapi_query_registers_typed_relationship_models():
    assert_transpile(
        '''
        from pydantic import BaseModel
        from pyjs.server import API, Relationship, Resource, query

        @js
        class Project(BaseModel):
            id: str
            name: str

        @js
        class Milestone(BaseModel):
            id: str
            title: str

        @js
        class MilestoneResource(Resource[Milestone]):
            pass

        @js
        class ProjectResource(Resource[Project]):
            milestones: Relationship[list[Milestone], MilestoneResource]

            @query
            async def list(self) -> list[Project]:
                raise RuntimeError("server only")

        @js
        class ApplicationAPI(API):
            projects: ProjectResource

        api = ApplicationAPI()

        async def main():
            projects = await api.projects.list()
            related = api.projects.related(
                projects[0],
                api.projects.milestones,
            )
            if related is None:
                return
            title = related[0].title
        ''',
        '''
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API, Resource } from './pyjs.server.js';
        import { JSONAPIDecoder as $JSONAPIDecoder } from './pyjs.server.jsonapi.js';
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export class Project extends BaseModel {
        }
        Project.__pyjs_required__ = ['id', 'name'];
        Project.__pyjs_fields__ = new Map([['id', 'str'], ['name', 'str']]);

        export class Milestone extends BaseModel {
        }
        Milestone.__pyjs_required__ = ['id', 'title'];
        Milestone.__pyjs_fields__ = new Map([['id', 'str'], ['title', 'str']]);

        export class MilestoneResource extends Resource {
        }


        export class ProjectResource extends Resource {

            async list() {
                const $document = new $JSONAPIDecoder(JSON.parse(await this._request('list', {})), new Map([['projects', Project], ['milestones', Milestone]]));
                return $document.data;
            }
        }
        Object.defineProperty(ProjectResource.prototype, 'milestones', {get() { return this.__pyjs_api_milestones ||= new MilestoneResource({path: this._path + '/milestones', transport: this._transport, timeout_ms: this._timeout_ms, relationship: true}); } });

        export class ApplicationAPI extends API {
        }
        Object.defineProperty(ApplicationAPI.prototype, 'projects', {get() { return this.__pyjs_api_projects ||= new ProjectResource({path: this._path + '/projects', transport: this._transport, timeout_ms: this._timeout_ms}); } });
        export const api = new ApplicationAPI();

        export async function main() {
            var projects = await api.projects.list();
            var related = api.projects.related($get_list_item(projects, 0), api.projects.milestones);
            if (related == null) {
                return;
            }
            var title = $get_list_item(related, 0).title;
        }
        ''',
    )


def test_called_api_operation_emits_typed_client_proxy():
    assert_transpile(
        """
        from pydantic import BaseModel
        from pyjs.server import API, Resource, query

        @js
        class Task(BaseModel):
            title: str

        @js
        class TaskResource(Resource[Task]):
            @query
            async def get(self, task_id: int) -> Task:
                raise RuntimeError("server only")

            @query
            async def first(self) -> Task:
                raise RuntimeError("server only")

        @js
        class ApplicationAPI(API):
            tasks: TaskResource

        api = ApplicationAPI()

        async def main():
            task = await api.tasks.get(1)
        """,
        """
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API, Resource } from './pyjs.server.js';
        import { JSONAPIDecoder as $JSONAPIDecoder } from './pyjs.server.jsonapi.js';

        export class Task extends BaseModel {
        }
        Task.__pyjs_required__ = ['title'];
        Task.__pyjs_fields__ = new Map([['title', 'str']]);

        export class TaskResource extends Resource {

            async get(task_id) {
                const $document = new $JSONAPIDecoder(JSON.parse(await this._request('get', {task_id: task_id})), new Map([['tasks', Task]]));
                return $document.data;
            }
        }


        export class ApplicationAPI extends API {
        }
        Object.defineProperty(ApplicationAPI.prototype, 'tasks', {get() { return this.__pyjs_api_tasks ||= new TaskResource({path: this._path + '/tasks', transport: this._transport, timeout_ms: this._timeout_ms}); } });
        export const api = new ApplicationAPI();

        export async function main() {
            var task = await api.tasks.get(1);
        }
        """,
    )


def test_client_api_subclass_inherits_operation_proxy():
    assert_transpile(
        '''
        from pydantic import BaseModel
        from pyjs.server import API, Resource, query

        @js
        class Task(BaseModel):
            title: str

        @js
        class BaseTaskResource(Resource[Task]):
            @query
            async def get(self, task_id: int) -> Task:
                raise RuntimeError("server only")

        @js
        class SpecializedTaskResource(BaseTaskResource):
            pass

        @js
        class ApplicationAPI(API):
            tasks: SpecializedTaskResource

        api = ApplicationAPI()

        async def main():
            task = await api.tasks.get(1)
        ''',
        '''
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API, Resource } from './pyjs.server.js';
        import { JSONAPIDecoder as $JSONAPIDecoder } from './pyjs.server.jsonapi.js';

        export class Task extends BaseModel {
        }
        Task.__pyjs_required__ = ['title'];
        Task.__pyjs_fields__ = new Map([['title', 'str']]);

        export class BaseTaskResource extends Resource {

            async get(task_id) {
                const $document = new $JSONAPIDecoder(JSON.parse(await this._request('get', {task_id: task_id})), new Map([['tasks', Task]]));
                return $document.data;
            }
        }


        export class SpecializedTaskResource extends BaseTaskResource {
        }


        export class ApplicationAPI extends API {
        }
        Object.defineProperty(ApplicationAPI.prototype, 'tasks', {get() { return this.__pyjs_api_tasks ||= new SpecializedTaskResource({path: this._path + '/tasks', transport: this._transport, timeout_ms: this._timeout_ms}); } });
        export const api = new ApplicationAPI();

        export async function main() {
            var task = await api.tasks.get(1);
        }
        ''',
    )


def test_api_operation_callback_retains_live_query_metadata():
    assert_transpile(
        """
        from pyjs.server import API, query

        @js
        class SearchAPI(API):
            @query
            async def search(self, term: str) -> str:
                raise RuntimeError("server only")

        api = SearchAPI()

        @js
        def receive(loader: callable):
            pass

        def main():
            receive(api.search)
        """,
        """
        import { API } from './pyjs.server.js';

        export class SearchAPI extends API {

            async search(term) {
                const $value = JSON.parse(await this._request('search', {term: term}));
                return $value;
            }
        }

        export const api = new SearchAPI();

        export function receive(loader) {
        }

        export function main() {
            receive(Object.assign(api.search.bind(api), {$operation: api._path + '/search', $arguments: ['term'], $decode: ($value) => $value}));
        }
        """,
    )


def test_operation_callback_reuses_the_recursive_result_decoder():
    assert_transpile(
        '''
        from pydantic import BaseModel
        from pyjs.server import API, query

        @js
        class Item(BaseModel):
            id: int

        @js
        class Unused(BaseModel):
            label: str

        @js
        class ExampleAPI(API):
            @query
            async def grouped(self) -> dict[int, list[Item]] | None:
                raise RuntimeError("server only")

        api = ExampleAPI()

        @js
        def receive(loader: callable):
            pass

        def main():
            receive(api.grouped)
        ''',
        '''
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API } from './pyjs.server.js';

        export class Item extends BaseModel {
        }
        Item.__pyjs_required__ = ['id'];
        Item.__pyjs_fields__ = new Map([['id', 'int']]);
        (globalThis.$pyjsModels ??= new Map()).set('_pyjs_source_.Item', Item);

        export class ExampleAPI extends API {

            async grouped() {
                const $value = JSON.parse(await this._request('grouped', {}));
                return this._decode_result($value, ["union",["dict","int",["list",["model","_pyjs_source_.Item"]]],"NoneType"]);
            }
        }

        export const api = new ExampleAPI();

        export function receive(loader) {
        }

        export function main() {
            receive(Object.assign(api.grouped.bind(api), {$operation: api._path + '/grouped', $arguments: [], $decode: ($value) => api._decode_result($value, ["union",["dict","int",["list",["model","_pyjs_source_.Item"]]],"NoneType"])}));
        }
        ''',
    )


def test_atomic_results_use_each_operation_decoder():
    source = textwrap.dedent(
        r'''
        from typing import cast

        from pydantic import BaseModel

        from pyjs import js
        from pyjs.server import (
            API,
            ClientTransport,
            TransportResponse,
            mutation,
        )

        @js
        class Item(BaseModel):
            id: int

        @js
        class MemoryTransport(ClientTransport):
            async def request(
                self,
                url: str,
                body: str,
                timeout_ms: int = 0,
            ) -> TransportResponse:
                return TransportResponse(200, '[{"1":[{"id":9}]}]')

        @js
        class ExampleAPI(API):
            @mutation
            async def grouped(self) -> dict[int, list[Item]]:
                return {1: [Item(id=9)]}

        async def main():
            api = ExampleAPI(transport=MemoryTransport())
            batch = api.atomic().add(api.grouped)
            results = await batch.commit()
            grouped = cast(dict[int, list[Item]], results[0])
            print(grouped[1][0].id)
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
    assert result.stdout == "9\n"
    assert result.stderr == ""


def test_jsonapi_operation_callback_retains_its_document_decoder():
    assert_transpile(
        """
        from pydantic import BaseModel
        from pyjs.server import API, Resource, query

        @js
        class Task(BaseModel):
            id: int
            title: str

        @js
        class TaskResource(Resource[Task]):
            @query
            async def get(self, task_id: int) -> Task:
                raise RuntimeError("server only")

        @js
        class ApplicationAPI(API):
            tasks: TaskResource

        api = ApplicationAPI()

        @js
        def receive(loader: callable):
            pass

        def main():
            receive(api.tasks.get)
        """,
        """
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API, Resource } from './pyjs.server.js';
        import { JSONAPIDecoder as $JSONAPIDecoder } from './pyjs.server.jsonapi.js';

        export class Task extends BaseModel {
        }
        Task.__pyjs_required__ = ['id', 'title'];
        Task.__pyjs_fields__ = new Map([['id', 'int'], ['title', 'str']]);

        export class TaskResource extends Resource {

            async get(task_id) {
                const $document = new $JSONAPIDecoder(JSON.parse(await this._request('get', {task_id: task_id})), new Map([['tasks', Task]]));
                return $document.data;
            }
        }


        export class ApplicationAPI extends API {
        }
        Object.defineProperty(ApplicationAPI.prototype, 'tasks', {get() { return this.__pyjs_api_tasks ||= new TaskResource({path: this._path + '/tasks', transport: this._transport, timeout_ms: this._timeout_ms}); } });
        export const api = new ApplicationAPI();

        export function receive(loader) {
        }

        export function main() {
            receive((($receiver) => Object.assign($receiver.get.bind($receiver), {$operation: $receiver._path + '/get', $arguments: ['task_id'], $decode: ($value) => $receiver._decode_jsonapi($value, new Map([['tasks', Task]]))}))(api.tasks));
        }
        """,
    )


def test_api_operation_is_omitted_when_only_resource_is_referenced():
    assert_transpile(
        """
        from pydantic import BaseModel
        from pyjs.server import API, Resource, query

        @js
        class Task(BaseModel):
            title: str

        @js
        class TaskResource(Resource[Task]):
            @query
            async def get(self, task_id: int) -> Task:
                raise RuntimeError("server only")

            @query
            async def first(self) -> Task:
                raise RuntimeError("server only")

        @js
        class ApplicationAPI(API):
            tasks: TaskResource

        api = ApplicationAPI()

        def main():
            resource = api.tasks
        """,
        """
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API, Resource } from './pyjs.server.js';

        export class TaskResource extends Resource {
        }


        export class ApplicationAPI extends API {
        }
        Object.defineProperty(ApplicationAPI.prototype, 'tasks', {get() { return this.__pyjs_api_tasks ||= new TaskResource({path: this._path + '/tasks', transport: this._transport, timeout_ms: this._timeout_ms}); } });
        export const api = new ApplicationAPI();

        export function main() {
            var resource = api.tasks;
        }
        """,
    )


def test_unused_api_branch_is_omitted():
    assert_transpile(
        """
        from pydantic import BaseModel
        from pyjs.server import API, Relationship, Resource, query

        @js
        class Task(BaseModel):
            title: str

        @js
        class User(BaseModel):
            name: str

        @js
        class TaskResource(Resource[Task]):
            users: Relationship[list[User]]

            @query
            async def get(self, task_id: int) -> Task:
                raise RuntimeError("server only")

            @query
            async def first(self) -> Task:
                raise RuntimeError("server only")

        @js
        class UserResource(Resource[User]):
            @query
            async def get(self, user_id: int) -> User:
                raise RuntimeError("server only")

        @js
        class ApplicationAPI(API):
            tasks: TaskResource
            users: UserResource

        api = ApplicationAPI()

        async def main():
            task = await api.tasks.get(1)
        """,
        """
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API, Resource } from './pyjs.server.js';
        import { JSONAPIDecoder as $JSONAPIDecoder } from './pyjs.server.jsonapi.js';

        export class Task extends BaseModel {
        }
        Task.__pyjs_required__ = ['title'];
        Task.__pyjs_fields__ = new Map([['title', 'str']]);

        export class TaskResource extends Resource {

            async get(task_id) {
                const $document = new $JSONAPIDecoder(JSON.parse(await this._request('get', {task_id: task_id})), new Map([['tasks', Task]]));
                return $document.data;
            }
        }


        export class ApplicationAPI extends API {
        }
        Object.defineProperty(ApplicationAPI.prototype, 'tasks', {get() { return this.__pyjs_api_tasks ||= new TaskResource({path: this._path + '/tasks', transport: this._transport, timeout_ms: this._timeout_ms}); } });
        export const api = new ApplicationAPI();

        export async function main() {
            var task = await api.tasks.get(1);
        }
        """,
    )


def test_relationship_resource_emits_nested_operation_proxy():
    assert_transpile(
        """
        from pydantic import BaseModel
        from pyjs.server import API, Relationship, Resource, include_paths, mutation

        @js
        class Task(BaseModel):
            title: str

        @js
        class Comment(BaseModel):
            body: str

        @js
        class CommentResource(Resource[Comment]):
            @mutation
            async def add(self, comment: Comment) -> Comment:
                raise RuntimeError("server only")

            @mutation
            async def remove(self, comment: Comment) -> Comment:
                raise RuntimeError("server only")

        @js
        class TaskResource(Resource[Task]):
            comments: Relationship[list[Comment], CommentResource]

        @js
        class ApplicationAPI(API):
            tasks: TaskResource

        api = ApplicationAPI()

        async def main():
            paths = include_paths(api.tasks, api.tasks.comments)
            comment = await api.tasks.comments.add(Comment(body="Nested"))
        """,
        """
        import { BaseModel } from './pyjs.lib.pydantic.v2.js';
        import { API, Resource, include_paths } from './pyjs.server.js';
        import { JSONAPIDecoder as $JSONAPIDecoder } from './pyjs.server.jsonapi.js';

        export class Comment extends BaseModel {
        }
        Comment.__pyjs_required__ = ['body'];
        Comment.__pyjs_fields__ = new Map([['body', 'str']]);

        export class CommentResource extends Resource {

            async add(comment) {
                const $document = new $JSONAPIDecoder(JSON.parse(await this._request('add', {comment: comment})), new Map([['comments', Comment]]));
                return $document.data;
            }
        }


        export class TaskResource extends Resource {
        }
        Object.defineProperty(TaskResource.prototype, 'comments', {get() { return this.__pyjs_api_comments ||= new CommentResource({path: this._path + '/comments', transport: this._transport, timeout_ms: this._timeout_ms, relationship: true}); } });

        export class ApplicationAPI extends API {
        }
        Object.defineProperty(ApplicationAPI.prototype, 'tasks', {get() { return this.__pyjs_api_tasks ||= new TaskResource({path: this._path + '/tasks', transport: this._transport, timeout_ms: this._timeout_ms}); } });
        export const api = new ApplicationAPI();

        export async function main() {
            var paths = include_paths(api.tasks, api.tasks.comments);
            var comment = await api.tasks.comments.add(new Comment({body: 'Nested'}));
        }
        """,
    )
