from pyjs.java import transpile_jvm
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
