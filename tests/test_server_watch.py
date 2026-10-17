import asyncio
import json

import pytest
from pydantic import BaseModel

import pyjs.server.watch as server_watch
from pyjs import js
from pyjs.server import (
    API,
    ClientTransport,
    LiveSession,
    Resource,
    TransportResponse,
    WatchedQuery,
    query,
)
from pyjs.testing.web import next_frame
from pyjs.web.events import Event, MessageEvent


async def settle_tasks():
    for _ in range(4):
        await asyncio.sleep(0)


def test_watched_query_coalesces_concurrent_refreshes():
    async def scenario():
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def load():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return calls

        query = WatchedQuery[int](load)
        first = asyncio.create_task(query.refresh())
        await started.wait()
        second = asyncio.create_task(query.refresh())

        assert query.loading is True
        assert calls == 1

        release.set()
        assert await asyncio.gather(first, second) == [1, 1]
        assert query.current == 1
        assert query.loading is False
        assert query.error is None
        assert query.stale is False

    asyncio.run(scenario())


def test_watched_query_caches_reads_and_refreshes_after_invalidation():
    async def scenario():
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            return calls

        query = WatchedQuery[int](load)

        assert await query.get() == 1
        assert await query.get() == 1
        assert calls == 1

        query.invalidate()
        assert query.stale is True
        assert await query.get() == 2
        assert calls == 2

    asyncio.run(scenario())


def test_watched_query_uses_a_seed_until_it_is_invalidated():
    async def scenario():
        calls = 0
        updates: list[int] = []

        async def load():
            nonlocal calls
            calls += 1
            return 8

        query = WatchedQuery[int](load).on_update(updates.append).seed(7)

        assert await query.get() == 7
        assert query.current == 7
        assert query.loaded is True
        assert query.stale is False
        assert calls == 0
        assert updates == []

        query.invalidate()

        assert await query.get() == 8
        assert calls == 1
        assert updates == [8]

    asyncio.run(scenario())


def test_watched_query_calls_its_loader_with_replaceable_arguments():
    async def scenario():
        calls: list[tuple[str, int]] = []

        async def load(prefix: str, number: int):
            calls.append((prefix, number))
            return prefix + str(number)

        query = WatchedQuery[str](load, "issue-", 1)

        assert await query.get() == "issue-1"
        assert query.arguments == ["issue-", 1]
        assert query.set_args("project-", 2) is query
        assert query.stale is True
        assert await query.reload() == "project-2"
        assert calls == [("issue-", 1), ("project-", 2)]

    asyncio.run(scenario())


def test_watched_query_describes_a_bound_api_operation():
    class SearchAPI(API):
        @query
        async def search(self, term: str, limit: int) -> str:
            return term[:limit]

    api = SearchAPI("/rpc")
    watched = WatchedQuery[str](api.search, "compiler", 4)

    assert watched.operation_path == "/rpc/search"
    assert watched.argument_names == ["term", "limit"]
    assert watched._live_request(3, "/rpc") == {
        "arguments": {"limit": 4, "term": "compiler"},
        "generation": 0,
        "id": 3,
        "operation": "search",
    }
    assert watched._live_request(3, "/other") is None


def test_watched_query_accepts_a_current_live_result():
    async def load():
        return 1

    updates = []
    query = WatchedQuery[int](load).on_update(updates.append)
    query.invalidate()

    query._accept_live(query._generation, 7)

    assert query.current == 7
    assert query.loaded is True
    assert query.stale is False
    assert query.error is None
    assert updates == [7]


def test_watched_query_refreshes_after_an_obsolete_live_result():
    async def scenario():
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            return calls

        query = WatchedQuery[int](load)
        query.invalidate()
        query._accept_live(query._generation - 1, 99)

        assert await query.get() == 1
        await asyncio.sleep(0)
        assert query.current == 1
        assert query.stale is False
        assert calls == 1

    asyncio.run(scenario())


def test_watched_query_notifies_its_update_hook_after_each_load():
    async def scenario():
        calls = 0
        updates: list[int] = []

        async def load():
            nonlocal calls
            calls += 1
            return calls

        query = WatchedQuery[int](load).on_update(updates.append)

        assert await query.get() == 1
        query.invalidate()
        assert await query.get() == 2
        assert updates == [1, 2]

    asyncio.run(scenario())


def test_watched_query_retains_update_hook_errors():
    async def scenario():
        async def load():
            return 1

        def reject(value: int):
            raise ValueError(f"Cannot display {value}")

        query = WatchedQuery[int](load).on_update(reject)

        with pytest.raises(ValueError, match="Cannot display 1"):
            await query.get()
        assert isinstance(query.error, ValueError)
        assert query.current == 1
        assert query.loaded is True

    asyncio.run(scenario())


def test_watched_query_can_cache_none_as_a_loaded_value():
    async def scenario():
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            return None

        query = WatchedQuery[object | None](load)

        assert await query.get() is None
        assert await query.get() is None
        assert query.loaded is True
        assert calls == 1

    asyncio.run(scenario())


def test_watched_query_retains_errors_and_can_retry():
    async def scenario():
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ValueError("load failed")
            return calls

        query = WatchedQuery[int](load)

        with pytest.raises(ValueError, match="load failed") as caught:
            await query.refresh()
        assert query.error is caught.value
        assert query.loading is False
        assert query.stale is True

        assert await query.refresh() == 2
        assert query.error is None
        assert query.current == 2

    asyncio.run(scenario())


def test_invalidation_during_a_request_keeps_the_result_stale():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        updates: list[int] = []

        async def load():
            started.set()
            await release.wait()
            return 1

        query = WatchedQuery[int](load).on_update(updates.append)
        pending = asyncio.create_task(query.refresh())
        await started.wait()
        query.invalidate()
        release.set()

        assert await pending == 1
        assert query.current == 1
        assert query.stale is True
        assert updates == []

    asyncio.run(scenario())


def test_reload_restarts_an_obsolete_in_flight_request():
    async def scenario():
        calls = 0
        selected = 1
        started = asyncio.Event()
        release = asyncio.Event()
        updates: list[int] = []

        async def load():
            nonlocal calls
            calls += 1
            value = selected
            if calls == 1:
                started.set()
                await release.wait()
            return value

        query = WatchedQuery[int](load).on_update(updates.append)
        first = asyncio.create_task(query.refresh())
        await started.wait()
        selected = 2
        latest = asyncio.create_task(query.reload())
        release.set()

        assert await first == 1
        assert await latest == 2
        assert calls == 2
        assert query.current == 2
        assert query.stale is False
        assert updates == [2]

    asyncio.run(scenario())


def test_live_session_refreshes_only_matching_watched_queries():
    async def scenario():
        issue_calls = 0
        project_calls = 0

        async def load_issues():
            nonlocal issue_calls
            issue_calls += 1
            return issue_calls

        async def load_projects():
            nonlocal project_calls
            project_calls += 1
            return project_calls

        issues = WatchedQuery[int](load_issues)
        projects = WatchedQuery[int](load_projects)
        await issues.get()
        await projects.get()
        session = LiveSession(autostart=False)
        issues.watch(session, "issues")
        projects.watch(session, "projects")

        session._receive(
            {
                "sequence": 1,
                "topics": ["issues"],
                "type": "invalidate",
            }
        )
        await settle_tasks()

        assert issues.current == 2
        assert projects.current == 1
        assert session.sequence == 1

        session._receive(
            {
                "sequence": 1,
                "topics": ["*"],
                "type": "invalidate",
            }
        )
        await settle_tasks()
        assert issue_calls == 2
        assert project_calls == 1

        session._receive(
            {
                "sequence": 2,
                "topics": ["*"],
                "type": "resync",
            }
        )
        await settle_tasks()
        assert issues.current == 3
        assert projects.current == 2

        session._receive(
            {
                "sequence": 0,
                "topics": ["*"],
                "type": "resync",
            }
        )
        await settle_tasks()
        assert issues.current == 4
        assert projects.current == 3
        assert session.sequence == 0

    asyncio.run(scenario())


def test_live_session_serializes_batches_and_replaces_queued_query_arguments():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        class RecordingSession(LiveSession):
            def __init__(self):
                super().__init__(autostart=False)
                self.batches = []
                self.active = 0
                self.maximum_active = 0

            async def _refresh_results(self, queries):
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                self.batches.append(queries)
                if len(self.batches) == 1:
                    started.set()
                    await release.wait()
                self.active -= 1

        class SearchAPI(API):
            @query
            async def search(self, term: str) -> str:
                return term

        session = RecordingSession()
        watched = WatchedQuery[str](SearchAPI().search, "first").watch(
            session,
            "results",
        )

        session._receive(
            {"sequence": 1, "topics": ["results"], "type": "invalidate"}
        )
        await started.wait()

        watched.set_args("second")
        session._receive(
            {"sequence": 2, "topics": ["results"], "type": "invalidate"}
        )
        watched.set_args("third")
        session._receive(
            {"sequence": 3, "topics": ["results"], "type": "invalidate"}
        )
        release.set()
        while session._result_refreshing:
            await asyncio.sleep(0)

        assert session.maximum_active == 1
        assert len(session.batches) == 2
        assert session.batches[0][0]["arguments"] == {"term": "first"}
        assert session.batches[1][0]["arguments"] == {"term": "third"}
        assert session._result_queries == []

    asyncio.run(scenario())


def test_live_session_accepts_results_delivered_by_the_event_stream():
    class SearchAPI(API):
        @query
        async def search(self, term: str) -> str:
            raise AssertionError("The direct result must not call the loader.")

    updates: list[str] = []
    session = LiveSession(autostart=False)
    watched = (
        WatchedQuery[str](SearchAPI().search, "compiler")
        .on_update(updates.append)
        .watch(session, "results")
    )

    session._receive(
        {
            "results": [
                {
                    "generation": 0,
                    "id": 1,
                    "value": "transpiler",
                }
            ],
            "sequence": 1,
            "topics": ["results"],
            "type": "result",
        }
    )

    assert watched.current == "transpiler"
    assert watched.loaded is True
    assert watched.stale is False
    assert updates == ["transpiler"]
    assert session._result_queries == []


def test_live_session_falls_back_when_a_direct_result_is_obsolete():
    class RecordingSession(LiveSession):
        def __init__(self):
            super().__init__(autostart=False)
            self.queued = []

        def _start_results(self):
            self.queued = list(self._result_queries)

    class SearchAPI(API):
        @query
        async def search(self, term: str) -> str:
            return term

    session = RecordingSession()
    watched = WatchedQuery[str](SearchAPI().search, "current").watch(
        session,
        "results",
    )
    watched.invalidate()

    session._receive(
        {
            "results": [
                {"generation": 0, "id": 1, "value": "obsolete"}
            ],
            "sequence": 1,
            "topics": ["results"],
            "type": "result",
        }
    )

    assert watched.current is None
    assert watched.stale is True
    assert session.queued == [
        {
            "arguments": {"term": "current"},
            "generation": 2,
            "id": 1,
            "operation": "search",
        }
    ]


def test_live_result_waits_out_an_older_in_flight_query(monkeypatch):
    async def scenario():
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()

        class SearchAPI(API):
            @query
            async def search(self, term: str) -> str:
                nonlocal calls
                calls += 1
                if calls == 1:
                    started.set()
                    await release.wait()
                return term + str(calls)

        class Response:
            ok = True

            def __init__(self, body: str):
                request = json.loads(body)
                query = request["queries"][0]
                self.result = json.dumps(
                    {
                        "results": [
                            {
                                "generation": query["generation"],
                                "id": query["id"],
                                "value": "streamed",
                            }
                        ]
                    }
                )

            async def text(self):
                return self.result

        async def fetch(path, options):
            return Response(options["body"])

        monkeypatch.setattr(server_watch, "fetch", fetch)
        session = LiveSession(autostart=False)
        watched = WatchedQuery[str](SearchAPI().search, "result-").watch(
            session,
            "results",
        )
        pending = asyncio.create_task(watched.refresh())
        await started.wait()

        session._receive(
            {
                "results": [
                    {"generation": 0, "id": 1, "value": "direct"}
                ],
                "sequence": 1,
                "topics": ["results"],
                "type": "result",
            }
        )
        await asyncio.sleep(0)
        release.set()
        await pending
        while watched.stale or session._result_refreshing:
            await asyncio.sleep(0)

        assert watched.current == "result-2"
        assert watched.stale is False
        assert calls == 2

    asyncio.run(scenario())


def test_live_session_builds_topic_aware_subscription_queries():
    class SearchAPI(API):
        @query
        async def search(self, term: str) -> str:
            return term

    session = LiveSession("/rpc", autostart=False)
    WatchedQuery[str](SearchAPI("/rpc").search, "compiler").watch(
        session,
        "issues",
        "comments",
    )

    assert session._subscription_queries() == [
        {
            "arguments": {"term": "compiler"},
            "generation": 0,
            "id": 1,
            "operation": "search",
            "topics": ["issues", "comments"],
        }
    ]


def test_live_session_infers_resource_topics_for_operations():
    class Item(BaseModel):
        name: str

    class InventoryResource(Resource[Item]):
        @query
        async def list(self) -> list[Item]:
            return []

    class AccountResource(Resource[Item]):
        inventory: InventoryResource

    class ApplicationAPI(API):
        account: AccountResource

    session = LiveSession("/rpc", autostart=False)
    WatchedQuery[list[Item]](
        ApplicationAPI("/rpc").account.inventory.list
    ).watch(session)

    assert session._subscription_queries() == [
        {
            "arguments": {},
            "generation": 0,
            "id": 1,
            "operation": "account.inventory.list",
            "topics": ["account.inventory"],
        }
    ]


def test_live_session_uses_wildcard_for_plain_and_root_operation_loaders():
    async def plain_loader() -> str:
        return "plain"

    class SearchAPI(API):
        @query
        async def search(self) -> str:
            return "result"

    session = LiveSession("/rpc", autostart=False)
    plain = WatchedQuery[str](plain_loader).watch(session)
    root = WatchedQuery[str](SearchAPI("/rpc").search).watch(session)

    assert session._watches[0].topics == ["*"]
    assert session._watches[1].topics == ["*"]
    assert plain is not root


def test_live_session_resynchronizes_when_a_watch_is_added_later():
    class RecordingSession(LiveSession):
        def __init__(self):
            super().__init__(autostart=False)
            self.started = 0
            self.autostart = True

        def _start_subscription_sync(self):
            self.started += 1

    class SearchAPI(API):
        @query
        async def search(self, term: str) -> str:
            return term

    session = RecordingSession()
    watched = WatchedQuery[str](SearchAPI().search, "first").watch(
        session,
        "results",
    )

    assert session.started == 1
    assert session._subscription_version == 1

    watched.set_args("second")

    assert session.started == 2
    assert session._subscription_version == 2


def test_live_session_refreshes_an_unloaded_query():
    async def scenario():
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            return calls

        query = WatchedQuery[int](load)
        session = LiveSession(autostart=False)
        query.watch(session)

        session._receive(
            {
                "sequence": 1,
                "topics": ["anything"],
                "type": "invalidate",
            }
        )
        await settle_tasks()

        assert query.stale is False
        assert query.loaded is True
        assert query.current == 1
        assert calls == 1

    asyncio.run(scenario())


def test_live_session_retains_refresh_errors_without_failing_delivery():
    async def scenario():
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("refresh failed")
            return calls

        query = WatchedQuery[int](load)
        await query.get()
        session = LiveSession(autostart=False)
        query.watch(session)

        session._receive(
            {
                "sequence": 1,
                "topics": ["*"],
                "type": "invalidate",
            }
        )
        await settle_tasks()

        assert isinstance(query.error, ValueError)
        assert query.stale is True
        assert query.current == 1

    asyncio.run(scenario())


def test_live_session_stops_polling_after_authorization_is_rejected(
    monkeypatch,
):
    async def scenario():
        class Response:
            ok = False
            status = 403

        async def fetch(path):
            return Response()

        monkeypatch.setattr(server_watch, "fetch", fetch)
        session = LiveSession(autostart=False)
        session.transport = "poll"

        await session._poll()

        assert session._closed is True
        assert session.transport == "stopped"

    asyncio.run(scenario())


def test_live_session_reloads_after_invalidation_during_refresh():
    async def scenario():
        calls = 0
        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def load():
            nonlocal calls
            calls += 1
            if calls == 2:
                refresh_started.set()
                await release_refresh.wait()
            return calls

        query = WatchedQuery[int](load)
        await query.get()
        session = LiveSession(autostart=False)
        query.watch(session)

        session._receive(
            {
                "sequence": 1,
                "topics": ["*"],
                "type": "invalidate",
            }
        )
        await refresh_started.wait()
        session._receive(
            {
                "sequence": 2,
                "topics": ["*"],
                "type": "invalidate",
            }
        )
        release_refresh.set()
        await settle_tasks()

        assert calls == 3
        assert query.current == 3
        assert query.stale is False

    asyncio.run(scenario())


def test_live_session_ignores_non_message_events_and_non_string_data():
    session = LiveSession(autostart=False)

    session._receive_event(Event("invalidate"))
    session._receive_event(MessageEvent("invalidate", data=1))

    assert session.sequence == 0


def test_live_session_normalizes_its_path_and_closes_sse():
    session = LiveSession("/api/", autostart=False)

    assert session.path == "/api"
    assert session.transport == "stopped"

    session.start()
    assert session.transport == "sse"
    assert session._source is not None

    session.close()
    assert session.transport == "stopped"
    assert session._source is None

    session.start()
    assert session.transport == "sse"
    assert session._source is not None
    assert session._closed is False
    session.close()


@pytest.mark.parametrize("status", [200, 500])
def test_closed_live_session_does_not_finish_opening_a_subscription(status):
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingTransport(ClientTransport):
            async def request(
                self,
                url: str,
                body: str,
                timeout_ms: int = 0,
            ) -> TransportResponse:
                started.set()
                await release.wait()
                return TransportResponse(status, '{"subscription":"ready"}')

        class SearchAPI(API):
            @query
            async def search(self) -> str:
                return "ready"

        api = SearchAPI(transport=BlockingTransport())
        session = api.live_session()
        WatchedQuery[str](api.search).watch(session, "results")
        await started.wait()

        session.close()
        release.set()
        await settle_tasks()

        assert session.transport == "stopped"
        assert session._source is None
        assert session._closed is True

    asyncio.run(scenario())


@js
class BrowserQueryLoader:
    def __init__(self):
        self.calls = 0
        self.updated = 0

    async def load(self) -> int:
        self.calls += 1
        await next_frame()
        return self.calls

    async def load_by(self, increment: int) -> int:
        self.calls += increment
        await next_frame()
        return self.calls

    def update(self, value: int):
        self.updated = value


@pytest.mark.pyjs_web
@js
async def test_watched_query_runs_in_the_browser():
    loader = BrowserQueryLoader()
    query = WatchedQuery[int](lambda: loader.load()).on_update(loader.update)

    query.refresh()
    query.refresh()
    assert query.loading is True
    assert loader.calls == 1

    await next_frame()
    await next_frame()
    assert query.current == 1
    assert loader.updated == 1
    assert query.loading is False

    assert await query.get() == 1
    query.invalidate()
    assert await query.get() == 2
    assert loader.calls == 2
    assert loader.updated == 2


@pytest.mark.pyjs_web
@js
async def test_watched_query_replaces_arguments_in_the_browser():
    loader = BrowserQueryLoader()
    query = WatchedQuery[int](loader.load_by, 2)

    assert await query.get() == 2
    query.set_args(3)
    assert await query.reload() == 5
    assert query.arguments == [3]


@pytest.mark.pyjs_web
@js
async def test_live_session_routes_browser_message_events():
    loader = BrowserQueryLoader()
    query = WatchedQuery[int](lambda: loader.load()).on_update(loader.update)
    await query.get()
    session = LiveSession(autostart=False)
    query.watch(session, "issues")

    session._receive_event(
        MessageEvent(
            "invalidate",
            data=(
                '{"sequence":1,"topics":["issues"],'
                '"type":"invalidate"}'
            ),
        )
    )
    await next_frame()
    await next_frame()

    assert query.current == 2
    assert loader.updated == 2
    assert query.stale is False
    assert session.sequence == 1
