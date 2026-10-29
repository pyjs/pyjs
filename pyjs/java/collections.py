"""JVM collection interfaces and specialized construction helpers."""

from pyjs import jvm
from pyjs.java import i32


class ListFromKeys[Source, Item]:
    def __init__(self, source: Source):
        self.result: list[Item] = []
        for key in source:
            self.result.append(key)


@jvm.native("java/util/List", interface=True)
class JavaList:
    def size(self) -> i32: ...
    def get(self, index: i32) -> object: ...


@jvm.native("java/util/Map", interface=True)
class JavaMap:
    def get(self, key: object) -> object | None: ...
