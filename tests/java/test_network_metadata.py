from tests.java.test_exceptions import run_jvm


def test_url_components_preserve_origin_validation_information(tmp_path):
    result = run_jvm('''
from pyjs.java.net import URL
def main() -> str:
    root = URL("https://example.test:8443/")
    assert root.getProtocol() == "https"
    assert root.getHost() == "example.test"
    assert root.getPort() == 8443
    assert URL("https://example.test").getPort() == -1
    assert root.getPath() == "/"
    assert root.getQuery() is None
    assert root.getRef() is None
    assert root.getUserInfo() is None
    qualified = URL("https://user:pass@example.test/path?query#fragment")
    assert qualified.getUserInfo() == "user:pass"
    assert qualified.getPath() == "/path"
    assert qualified.getQuery() == "query"
    assert qualified.getRef() == "fragment"
    return "components"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "components"


def test_uri_authority_validation_has_a_catchable_native_error(tmp_path):
    result = run_jvm('''
from pyjs.java.net import URI, URL, URISyntaxException
def main() -> str:
    URL("https://example.test:8443/").toURI().parseServerAuthority()
    rejected = 0
    for source in ["https://exa mple.test", "https://%zz.test", "https://bad_host.test"]:
        try:
            URI(source).parseServerAuthority()
        except URISyntaxException:
            rejected += 1
    assert rejected == 3
    return "validated"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "validated"
