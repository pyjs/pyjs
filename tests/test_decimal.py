import pytest

from pyjs.stdlib import Decimal
from tests.semantics.helpers import assert_semantics


def test_decimal_uses_exact_cpython_arithmetic():
    left = Decimal("1.20")
    right = Decimal("2.3")

    assert str(left + right) == "3.50"
    assert str(left - right) == "-1.10"
    assert str(left * right) == "2.760"
    assert str(Decimal("0") * Decimal("-1")) == "0"
    assert str(-Decimal("0")) == "0"
    assert str(Decimal("-1") * Decimal("0.00")) == "0.00"
    assert str(-Decimal("0.00")) == "0.00"
    assert str(Decimal("1.20") - Decimal("1.20")) == "0.00"
    assert left < right
    assert left == Decimal("1.2")
    assert left != 1


def test_decimal_rejects_deferred_exponent_notation():
    with pytest.raises(ValueError, match="exponent notation"):
        Decimal("1e2")


@pytest.mark.parametrize("value", (1.0, 1.5, "1_000", "1_0.0"))
def test_decimal_rejects_values_outside_its_exact_constructor_grammar(value):
    with pytest.raises(TypeError):
        Decimal(value)


@pytest.mark.parametrize("value", (True, "NaN", "Infinity", "-0.00"))
def test_decimal_rejects_values_outside_the_shared_subset(value):
    with pytest.raises((TypeError, ValueError)):
        Decimal(value)


def test_decimal_semantics_match_javascript():
    assert_semantics(
        """
        from pyjs import js
        from pyjs.stdlib import Decimal

        @js
        def make(label: str, value: str) -> Decimal:
            print(label)
            return Decimal(value)

        left = Decimal("1.20")
        right = Decimal("2.3")
        print(Decimal(".5"))
        print(left + right)
        print(left - right)
        print(left * right)
        print(Decimal("0") * Decimal("-1"))
        print(-Decimal("0"))
        print(Decimal("-1") * Decimal("0.00"))
        print(-Decimal("0.00"))
        print(Decimal("1.20") - Decimal("1.20"))
        print(-left)
        print("zero" if Decimal("0.00") else "empty")
        print("nonzero" if Decimal("0.01") else "empty")
        print(left < right, left <= Decimal("1.2"))
        print(right > left, right >= Decimal("2.30"))
        print(left == Decimal("1.2"), left != right, left == 1)
        print(make("left", "1") == make("right", "1"))
        """
    )


def test_decimal_rejections_raise_the_same_exception_class():
    assert_semantics(
        """
        from pyjs import js
        from pyjs.stdlib import Decimal

        @js
        def reject(value: str) -> None:
            try:
                Decimal(value)
            except ValueError:
                print("value")
            except TypeError:
                print("type")

        reject("1e2")
        reject("NaN")
        reject("NaN123")
        reject("Infinity")
        reject("bad")
        """
    )


def test_decimal_subclasses_construct_and_preserve_their_type():
    assert_semantics(
        """
        from pyjs import js
        from pyjs.stdlib import Decimal

        @js
        class Money(Decimal):
            pass

        @js
        def main() -> None:
            value = Money(Decimal("1.20"))
            plain = Decimal("1.20")
            print(value)
            print(isinstance(value + Money("0.80"), Money))
            print(value == plain, plain == value)
            print(value != plain, plain != value)

        main()
        """
    )
