"""Native styled text; range offsets are UTF-16 code units."""

from pyjs import jvm
from pyjs.android import CharSequence, Editable
from pyjs.android import Spannable as Spannable
from pyjs.android import Spanned as Spanned
from pyjs.java import i32


@jvm.native("android/text/SpannableString")
class SpannableString(Spannable):
    def __init__(self, source: CharSequence) -> None: ...


@jvm.native("android/text/SpannableStringBuilder")
class SpannableStringBuilder(Editable):
    def __init__(self, source: CharSequence) -> None: ...

    def append(self, text: CharSequence) -> SpannableStringBuilder: ...

    def replace(self, start: i32, end: i32, text: CharSequence) -> SpannableStringBuilder: ...


@jvm.native("android/text/style/StyleSpan")
class StyleSpan:
    def __init__(self, style: i32) -> None: ...

    @jvm.native("android/text/style/StyleSpan", name="getStyle", invocation="virtual")
    def get_style(self) -> i32: ...


@jvm.native("android/text/style/StrikethroughSpan")
class StrikethroughSpan:
    def __init__(self) -> None: ...


@jvm.native("android/text/style/TypefaceSpan")
class TypefaceSpan:
    def __init__(self, family: str | None) -> None: ...

    @jvm.native("android/text/style/TypefaceSpan", name="getFamily", invocation="virtual")
    def get_family(self) -> str | None: ...
