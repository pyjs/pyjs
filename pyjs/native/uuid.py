"""Native-compatible declarations for UUID values."""


_HEX_DIGITS = "0123456789abcdef"


def _normalized_hex(value: str) -> str:
    normalized = value.replace("urn:", "").replace("uuid:", "")
    normalized = normalized.strip("{}").replace("-", "")
    if len(normalized) != 32:
        raise ValueError("badly formed hexadecimal UUID string")
    for character in normalized.lower():
        if character not in _HEX_DIGITS:
            raise ValueError(f"invalid literal for int() with base 16: {normalized!r}")
    return normalized.lower()


class UUID:
    def __init__(self, hex: str) -> None:
        self._hex = _normalized_hex(hex)

    @property
    def hex(self) -> str:
        return self._hex

    def __str__(self) -> str:
        value = self.hex
        return (
            value[:8]
            + "-"
            + value[8:12]
            + "-"
            + value[12:16]
            + "-"
            + value[16:20]
            + "-"
            + value[20:]
        )

    def __eq__(self, other: UUID) -> bool:
        return self.hex == other.hex

    def __hash__(self) -> int:
        return hash(self.hex)


__all__ = ["UUID"]
