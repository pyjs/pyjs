"""Analysis declarations for scalar enum bases; execution uses stdlib enums."""


class StrEnum(str):
    @property
    def name(self) -> str:
        return ""

    @property
    def value(self) -> str:
        return str(self)


class IntEnum(int):
    @property
    def name(self) -> str:
        return ""

    @property
    def value(self) -> int:
        return int(self)


__all__ = ["IntEnum", "StrEnum"]
