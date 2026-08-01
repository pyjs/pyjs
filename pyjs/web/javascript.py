from pyjs import js


@js(builtin=True)
class JSON:
    @staticmethod
    def parse(value: str) -> object: ...

    @staticmethod
    def stringify(value: object) -> str: ...


@js(builtin=True)
def encodeURIComponent(value: str) -> str: ...
