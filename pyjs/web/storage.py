from pyjs import js


@js.native
class Navigator:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Navigator

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.storage: StorageManager = None


navigator = Navigator()
js.native(navigator)


@js.dictionary
class StorageEstimate:
    """WebIDL source: @webref/idl/storage.idl"""

    def __init__(self, quota: int | None = None, usage: int | None = None):
        if quota is not None:
            self.quota = quota
        if usage is not None:
            self.usage = usage


@js.native
class StorageManager:
    """WebIDL source: @webref/idl/storage.idl

    MDN: https://developer.mozilla.org/docs/Web/API/StorageManager

    Browser support: Chrome 55, Safari 15.2"""

    async def estimate(self) -> StorageEstimate: ...

    async def persist(self) -> bool: ...

    async def persisted(self) -> bool: ...
