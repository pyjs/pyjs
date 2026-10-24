"""Strict JSON tokens for schema-directed JVM and Android decoding."""

from pyjs import jvm, uint16
from pyjs.java import i32, parse_double


@jvm.native("java/lang/String")
class _UTF16:
    # Python indexing counts code points. Using it repeatedly over a Java
    # String would rescan the prefix and make the decoder quadratic.
    def __init__(self, value: str):
        self.data = value.encode("utf-16-le", "surrogatepass")

    def length(self) -> i32:
        return i32(len(self.data) // 2)

    @jvm.native("java/lang/String", name="charAt", invocation="virtual")
    def unit(self, index: i32) -> uint16:
        position = int(index) * 2
        return uint16(self.data[position] + 256 * self.data[position + 1])

    @jvm.native("java/lang/String", name="substring", invocation="virtual")
    def slice(self, start: i32, end: i32) -> str:
        return self.data[int(start) * 2:int(end) * 2].decode("utf-16-le", "surrogatepass")


def _hex4(value: int) -> str:
    digits = "0123456789abcdef"
    return (digits[value // 4096] + digits[value // 256 % 16]
            + digits[value // 16 % 16] + digits[value % 16])


def quote(value: str) -> str:
    """Encode a JSON string using ASCII escapes, preserving surrogate values."""
    parts = ['"']
    start = 0
    text = _UTF16(value)
    length = int(text.length())
    for index in range(length):
        code = int(text.unit(i32(index)))
        character = chr(code)
        escaped = ""
        if character == '"' or character == "\\":
            escaped = "\\" + character
        elif code == 8:
            escaped = "\\b"
        elif code == 9:
            escaped = "\\t"
        elif code == 10:
            escaped = "\\n"
        elif code == 12:
            escaped = "\\f"
        elif code == 13:
            escaped = "\\r"
        elif code < 32 or code >= 127:
            escaped = "\\u" + _hex4(code)
        if escaped != "":
            parts.append(text.slice(i32(start), i32(index)))
            parts.append(escaped)
            start = index + 1
    parts.append(text.slice(i32(start), i32(length)))
    parts.append('"')
    return "".join(parts)


class JSONReader:
    """Read typed values without constructing an untyped object tree.

    Call finish() after the root value. Number tokens retain their spelling;
    the schema decoder decides their numeric type and range. Unknown values
    can be skipped with a bounded nesting depth. Whitespace is JSON's four
    ASCII whitespace characters, not Python's broader Unicode whitespace.
    Diagnostic positions are UTF-16 code-unit offsets on both runtimes.
    """

    def __init__(self, source: str):
        self.source = _UTF16(source)
        self.length = int(self.source.length())
        self.position = 0

    def _peek(self) -> str:
        if self.position >= self.length:
            return ""
        return chr(int(self.source.unit(i32(self.position))))

    def _space(self) -> None:
        while self.position < self.length:
            value = self._peek()
            if value != " " and value != "\t" and value != "\r" and value != "\n":
                return
            self.position += 1

    def take(self, token: str) -> bool:
        """Consume an exact punctuation or literal token after whitespace."""
        self._space()
        if token == "":
            raise ValueError("JSON token must not be empty")
        end = self.position + int(_UTF16(token).length())
        if end > self.length or self.source.slice(i32(self.position), i32(end)) != token:
            return False
        self.position = end
        return True

    def expect(self, token: str) -> None:
        if not self.take(token):
            raise ValueError("Expected JSON token " + token + " at " + str(self.position))

    def finish(self) -> None:
        self._space()
        if self.position != self.length:
            raise ValueError("Unexpected JSON content at " + str(self.position))

    def _hex(self) -> int:
        result = 0
        for _ in range(4):
            value = self._peek()
            digit = -1
            if "0" <= value <= "9":
                digit = ord(value) - 48
            elif "a" <= value <= "f":
                digit = ord(value) - 87
            elif "A" <= value <= "F":
                digit = ord(value) - 55
            if digit < 0:
                raise ValueError("Invalid JSON Unicode escape at " + str(self.position))
            result = result * 16 + digit
            self.position += 1
        return result

    def string(self) -> str:
        self.expect('"')
        parts: list[str] = []
        start = self.position
        while self.position < self.length:
            value = self._peek()
            if value == '"':
                parts.append(self.source.slice(i32(start), i32(self.position)))
                self.position += 1
                return "".join(parts)
            if ord(value) < 32:
                raise ValueError("Unescaped JSON control character at " + str(self.position))
            if value != "\\":
                self.position += 1
                continue
            parts.append(self.source.slice(i32(start), i32(self.position)))
            self.position += 1
            escaped = self._peek()
            self.position += 1
            if escaped == '"' or escaped == "\\" or escaped == "/":
                parts.append(escaped)
            elif escaped == "b":
                parts.append("\b")
            elif escaped == "f":
                parts.append("\f")
            elif escaped == "n":
                parts.append("\n")
            elif escaped == "r":
                parts.append("\r")
            elif escaped == "t":
                parts.append("\t")
            elif escaped == "u":
                code = self._hex()
                if 55296 <= code <= 56319:
                    saved = self.position
                    if saved + 2 <= self.length and self.source.slice(i32(saved), i32(saved + 2)) == "\\u":
                        self.position += 2
                        low = self._hex()
                        if 56320 <= low <= 57343:
                            code = 65536 + (code - 55296) * 1024 + low - 56320
                        else:
                            self.position = saved
                parts.append(chr(code))
            else:
                raise ValueError("Invalid JSON escape at " + str(self.position - 1))
            start = self.position
        raise ValueError("Unterminated JSON string")

    def boolean(self) -> bool:
        if self.take("true"):
            return True
        if self.take("false"):
            return False
        raise ValueError("Expected JSON boolean at " + str(self.position))

    def number(self) -> str:
        self._space()
        start = self.position
        if self._peek() == "-":
            self.position += 1
        value = self._peek()
        if value == "0":
            self.position += 1
        elif "1" <= value <= "9":
            self._digits()
        else:
            raise ValueError("Expected JSON number at " + str(self.position))
        if self._peek() == ".":
            self.position += 1
            self._digits()
        value = self._peek()
        if value == "e" or value == "E":
            self.position += 1
            value = self._peek()
            if value == "+" or value == "-":
                self.position += 1
            self._digits()
        return self.source.slice(i32(start), i32(self.position))

    def _digits(self) -> None:
        start = self.position
        while "0" <= self._peek() <= "9":
            self.position += 1
        if self.position == start:
            raise ValueError("Expected JSON digit at " + str(self.position))

    def integer(self) -> int:
        """Read an integer token in the JVM's signed 64-bit range."""
        token = self.number()
        digits = token[1:] if token[0] == "-" else token
        for character in digits:
            if character < "0" or character > "9":
                raise ValueError("Expected JSON integer")
        limit = "9223372036854775808" if token[0] == "-" else "9223372036854775807"
        if len(digits) > 19 or len(digits) == 19 and digits > limit:
            raise ValueError("JSON integer exceeds the signed 64-bit range")
        return int(token)

    def floating(self) -> float:
        """Read a finite binary64 number; underflow follows JVM rounding."""
        value = parse_double(self.number())
        if value > 1.7976931348623157e308 or value < -1.7976931348623157e308:
            raise ValueError("JSON number exceeds the finite binary64 range")
        return value

    def skip(self, max_depth: int = 64) -> None:
        """Consume one unknown value, validating its complete JSON syntax."""
        if max_depth < 0:
            raise ValueError("JSON nesting limit exceeded")
        self._space()
        value = self._peek()
        if value == '"':
            self.string()
        elif self.take("{"):
            if max_depth == 0:
                raise ValueError("JSON nesting limit exceeded")
            if self.take("}"):
                return
            while True:
                self.string()
                self.expect(":")
                self.skip(max_depth - 1)
                if self.take("}"):
                    return
                self.expect(",")
        elif self.take("["):
            if max_depth == 0:
                raise ValueError("JSON nesting limit exceeded")
            if self.take("]"):
                return
            while True:
                self.skip(max_depth - 1)
                if self.take("]"):
                    return
                self.expect(",")
        elif not (self.take("null") or self.take("true") or self.take("false")):
            self.number()
