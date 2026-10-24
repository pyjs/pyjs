"""Native Java collection interfaces at erased object boundaries."""

from pyjs import jvm
from pyjs.java import i32


@jvm.native("java/util/List", interface=True)
class JavaList:
    def size(self) -> i32: ...
    def get(self, index: i32) -> object: ...


@jvm.native("java/util/Map", interface=True)
class JavaMap:
    def get(self, key: object) -> object | None: ...
