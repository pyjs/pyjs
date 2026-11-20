"""JVM collection interfaces and Python-authored construction helpers."""

from pyjs import jvm
from pyjs.java import i32


class ListFromIterable[Source, Item]:
    def __init__(self, source: Source):
        self.result: list[Item] = []
        for item in source:
            self.result.append(item)


@jvm.native("java/util/List", interface=True)
class JavaList:
    def size(self) -> i32: ...
    def get(self, index: i32) -> object: ...


@jvm.native("java/util/ArrayList")
class JavaArrayList(JavaList):
    def __init__(self) -> None: ...

    def add(self, value: object) -> bool: ...


@jvm.native("java/util/Map", interface=True)
class JavaMap:
    def get(self, key: object) -> object | None: ...
