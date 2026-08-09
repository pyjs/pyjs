from pyjs import js
from pyjs.web.events import EventTarget
from pyjs.web.files import Blob


@js(builtin=True)
class MediaSource(EventTarget):
    """WebIDL source: @webref/idl/media-source.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MediaSource

    Browser support: Chrome 31, Safari 8"""

    pass


@js(builtin=True)
class URL:
    """WebIDL source: @webref/idl/url.idl

    MDN: https://developer.mozilla.org/docs/Web/API/URL

    Browser support: Chrome 32, Safari 7"""

    def __init__(self, url: str, base: str | None = None):
        self.hash: str = ""
        self.host: str = ""
        self.hostname: str = ""
        self.href: str = ""
        self.origin: str = ""
        self.password: str = ""
        self.pathname: str = ""
        self.port: str = ""
        self.protocol: str = ""
        self.search: str = ""
        self.searchParams: URLSearchParams = None
        self.username: str = ""

    @staticmethod
    def canParse(url: str, base: str | None = None) -> bool: ...

    @staticmethod
    def createObjectURL(obj: Blob | MediaSource) -> str: ...

    @staticmethod
    def parse(url: str, base: str | None = None) -> URL | None: ...

    @staticmethod
    def revokeObjectURL(url: str) -> None: ...

    def toJSON(self) -> str: ...


@js(builtin=True)
class URLSearchParams:
    """WebIDL source: @webref/idl/url.idl

    MDN: https://developer.mozilla.org/docs/Web/API/URLSearchParams

    Browser support: Chrome 49, Safari 10.1"""

    def __init__(self, init: list[list[str]] | dict[str, str] | str = ""):
        self.size: int = 0

    def append(self, name: str, value: str) -> None: ...

    def delete(self, name: str, value: str | None = None) -> None: ...

    def get(self, name: str) -> str | None: ...

    def getAll(self, name: str) -> list[str]: ...

    def has(self, name: str, value: str | None = None) -> bool: ...

    def set(self, name: str, value: str) -> None: ...

    def sort(self) -> None: ...
