import pytest

from pyjs.java import transpile_jvm
from pyjs.java.api import class_info, validate_children
from pyjs.server import API, query
from tests.java.test_api_transport import django_endpoint as django_endpoint
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    run_jvm,
)

PROXY = '''
from pyjs import js
from pyjs.java import run_sync
from pyjs.server import API, mutation
from pyjs.server.transport import ClientTransport, TransportResponse
from tests.java.json_models import Item

@js
class Catalog(API):
    @mutation
    async def save(self, item: Item, *, label: str = "default") -> Item:
        from intentionally_unavailable_backend import write_item
        write_item(item)
        raise RuntimeError("SERVER_IMPLEMENTATION_MUST_NOT_BE_BUNDLED")

@js
class Client(API):
    catalog: Catalog

class Transport(ClientTransport):
    async def request(self, url: str, body: str, timeout_ms: int = 0) -> TransportResponse:
        assert url == "https://example.test/api/catalog/save"
        assert timeout_ms == 1234
        assert body == '{"item":{"name":"snow","count":2},"label":"default"}'
        return TransportResponse(200, '{"name":"saved","count":3}')

async def execute() -> str:
    api = Client("https://example.test/api", transport=Transport(), timeout_ms=1234)
    result = await api.catalog.save(Item(name="snow", count=2))
    return result.name + ":" + str(result.count)

def main() -> str:
    return run_sync(execute())
'''


def test_jvm_generates_nested_typed_api_proxies(tmp_path):
    result = run_jvm(PROXY, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "saved:3"


def test_proxy_artifact_excludes_server_method_body():
    compilation = transpile_jvm(PROXY)
    assert b"SERVER_IMPLEMENTATION_MUST_NOT_BE_BUNDLED" not in b"".join(compilation.classes.values())


def test_typed_api_proxy_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(PROXY, tmp_path)


def test_generated_proxy_reaches_real_django_contract(tmp_path, django_endpoint):
    headers = [("Cookie", "csrftoken=" + "a" * 32), ("X-CSRFToken", "a" * 32),
               ("Authorization", "Bearer test-token")]
    source = f'''
from pyjs.java import run_sync
from pyjs.server.jvm import JVMTransport
from tests.java.api_transport_contract import Draft, EchoAPI
async def execute() -> str:
    api = EchoAPI({django_endpoint!r}, transport=JVMTransport({headers!r}), timeout_ms=3000)
    result = await api.echo(Draft(title="é😀雪"))
    return result.title + ":" + str(result.count)
def main() -> str:
    return run_sync(execute())
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "é😀雪:0"


@pytest.mark.parametrize(("csrf", "credential", "title", "status", "location"), [
    (False, True, "valid", 403, ""),
    (True, False, "valid", 403, ""),
    (True, True, "", 422, "draft|title"),
])
def test_generated_proxy_retains_django_errors(tmp_path, django_endpoint, csrf, credential, title, status, location):
    headers = []
    if csrf:
        headers.extend([("Cookie", "csrftoken=" + "a" * 32), ("X-CSRFToken", "a" * 32)])
    if credential:
        headers.append(("Authorization", "Bearer test-token"))
    source = f'''
from pyjs.java import run_sync
from pyjs.server.errors import OperationError
from pyjs.server.jvm import JVMTransport
from tests.java.api_transport_contract import Draft, EchoAPI
async def execute() -> str:
    api = EchoAPI({django_endpoint!r}, transport=JVMTransport({headers!r}), timeout_ms=3000)
    try:
        await api.echo(Draft(title={title!r}))
    except OperationError as error:
        issue = error.issues[0]
        assert issue.status == {status}
        assert len(issue.detail) > 0
        return "|".join(issue.location)
    return "accepted invalid request"
def main() -> str:
    return run_sync(execute())
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == location


def test_proxy_graph_rejects_cycles_and_excessive_expansion():
    class Leaf(API):
        pass
    assert validate_children(Leaf) == (1, 1)
    Leaf.__pyjs_api_children__["cycle"] = Leaf
    with pytest.raises(TypeError, match="acyclic"):
        validate_children(Leaf)
    Leaf.__pyjs_api_children__.clear()
    node = Leaf
    for depth in range(12):
        parent = type(f"Pair{depth}", (API,), {})
        parent.__pyjs_api_children__.update(left=node, right=node)
        node = parent
    with pytest.raises(TypeError, match="4096 constructed nodes"):
        validate_children(node)


def test_proxy_graph_allows_shared_subgraphs_but_bounds_depth():
    class Leaf(API):
        pass
    node = Leaf
    for depth in range(32):
        parent = type(f"Level{depth}", (API,), {})
        parent.__pyjs_api_children__["child"] = node
        node = parent
    with pytest.raises(TypeError, match="32 levels"):
        validate_children(node)


@pytest.mark.parametrize(("parameter", "message"), [
    ("*values: str", "statically named parameters"),
    ("values: list[str] = []", "finite scalar values"),
    ("_pyjs_reader: str", "conflicts with a generated codec binding"),
])
def test_proxy_parameter_boundaries(parameter, message):
    namespace = {"API": API, "query": query}
    exec(f"class Contract(API):\n    @query\n    async def read(self, {parameter}) -> str:\n        return ''", namespace)
    with pytest.raises(TypeError, match=message):
        class_info(namespace["Contract"])


def test_inherited_operations_decode_lists_nulls_and_scalar_defaults(tmp_path):
    source = '''
from pyjs import js
from pyjs.java import run_sync
from pyjs.server import API, action, query
from pyjs.server.transport import ClientTransport, TransportResponse
from tests.java.json_models import Item
@js
class Base(API):
    @query
    async def lookup(self, key: str, /, enabled: bool = True, *, _pyjs_value_1: str | None = None) -> list[Item]:
        raise RuntimeError("server only")
    @action
    async def clear(self) -> None:
        raise RuntimeError("server only")
@js
class Child(Base):
    pass
class Transport(ClientTransport):
    async def request(self, url: str, body: str, timeout_ms: int = 0) -> TransportResponse:
        if url.endswith("/lookup"):
            assert body == '{"key":"entry","enabled":true,"_pyjs_value_1":null}'
            return TransportResponse(200, '[{"name":"found","count":4}]')
        assert url.endswith("/clear")
        assert body == '{}'
        return TransportResponse(200, 'null')
async def execute() -> str:
    api = Child("https://example.test/api", transport=Transport())
    values = await api.lookup("entry")
    await api.clear()
    return values[0].name + ":" + str(values[0].count)
def main() -> str:
    return run_sync(execute())
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "found:4"


@pytest.mark.parametrize("name", ["str", "list", "dict", "int", "bool", "float", "ValueError"])
def test_proxy_parameters_do_not_shadow_generated_builtin_bindings(tmp_path, name):
    source = f'''
from pyjs.java import run_sync
from pyjs.server import API, mutation
from pyjs.server.transport import ClientTransport, TransportResponse
from tests.java.json_models import Item
class Client(API):
    @mutation
    async def echo(self, {name}: int) -> list[dict[str, Item | None]]:
        raise RuntimeError("server only")
class Transport(ClientTransport):
    async def request(self, url: str, body: str, timeout_ms: int = 0) -> TransportResponse:
        assert body == '{{"{name}":17}}'
        return TransportResponse(200, '[{{"item":{{"name":"saved","count":17}},"empty":null}}]')
async def execute() -> str:
    api = Client("https://example.test/api", transport=Transport())
    values = await api.echo({name}=17)
    assert values[0]["empty"] is None
    item = values[0]["item"]
    if item is None:
        return "missing"
    return item.name + ":" + str(item.count)
def main() -> str:
    return run_sync(execute())
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "saved:17"
