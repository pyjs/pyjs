from pyjs import js
from pyjs.web.files import File


@js.native
class Navigator:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Navigator

    Browser support: Chrome 1, Safari 1"""

    def canShare(self, data: ShareData | None = None) -> bool: ...

    async def share(self, data: ShareData | None = None) -> None: ...


navigator = Navigator()
js.native(navigator)


@js.dictionary
class ShareData:
    """WebIDL source: @webref/idl/web-share.idl"""

    def __init__(
        self,
        files: list[File] | None = None,
        text: str | None = None,
        title: str | None = None,
        url: str | None = None,
    ):
        if files is not None:
            self.files = files
        if text is not None:
            self.text = text
        if title is not None:
            self.title = title
        if url is not None:
            self.url = url
