import pytest

from pyjs import js

pytestmark = pytest.mark.pyjs_web


@js
def test_browser_pytest_raises_context_manager():
    with pytest.raises(ValueError, match="bad value") as caught:
        raise ValueError("bad value")

    assert str(caught.value) == "bad value"
    assert caught.type is ValueError
    assert caught.traceback is None

    with pytest.raises(AssertionError, match="DID NOT RAISE ValueError"):
        with pytest.raises(ValueError):
            pass

    with pytest.raises(AssertionError, match="Regex pattern did not match"):
        with pytest.raises(ValueError, match="wanted"):
            raise ValueError("actual")

    with pytest.raises(TypeError, match="wrong type"):
        with pytest.raises(ValueError):
            raise TypeError("wrong type")
