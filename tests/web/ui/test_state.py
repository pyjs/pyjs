import pytest

from pyjs import effect, state
from pyjs.web.domx import CustomElement, ref, span, tag


class ReactiveCounter(CustomElement):
    count = state(2)

    def __init__(self):
        super().__init__()
        self.output = ref(span())
        tag(self, self.output)

    @effect(count)
    def render_count(self):
        self.output.textContent = str(self.count)


class StateKinds(CustomElement):
    title = state("Ready")
    ratio = state(1.5)
    current_page = state(1)
    open = state(False)
    enabled = state(True)


class InitializedState(CustomElement):
    title = state("Default")

    def __init__(self):
        super().__init__()
        self.title = "Chosen"


@pytest.mark.pyjs_python
def test_direct_state_attributes_before_base_init_defer_effects():
    events = []

    class BeforeBase(CustomElement):
        count = state(7)

        def __init__(self):
            self.setAttribute("count", "3")
            self.removeAttribute("count")
            self.setAttribute("count", "4")
            events.append("before")
            super().__init__()

        @effect(count)
        def changed(self):
            events.append(self.count)

    element = BeforeBase()
    assert events == ["before", 7]
    assert element.count == 7
    element.count = 8
    assert events == ["before", 7, 8]


@pytest.mark.pyjs_python
def test_state_is_stored_on_the_element_and_runs_effects():
    counter = ReactiveCounter()

    assert counter.count == 2
    assert counter.getAttribute("count") == "2"
    assert counter.output.textContent == "2"

    counter.count = 3

    assert counter.getAttribute("count") == "3"
    assert counter.output.textContent == "3"

    counter.setAttribute("count", "4")

    assert counter.count == 4
    assert counter.output.textContent == "4"


@pytest.mark.pyjs_python
def test_state_converts_supported_scalars_and_maps_names_to_attributes():
    element = StateKinds()

    assert element.title == "Ready"
    assert element.ratio == 1.5
    assert element.current_page == 1
    assert element.getAttribute("current-page") == "1"
    assert not element.open
    assert not element.hasAttribute("open")
    assert element.enabled
    assert element.hasAttribute("enabled")

    element.open = True
    element.setAttribute("ratio", "2.25")

    assert element.open
    assert element.getAttribute("open") == ""
    assert element.ratio == 2.25

    element.open = False
    element.enabled = False

    assert not element.open
    assert not element.hasAttribute("open")
    assert not element.enabled
    assert not element.hasAttribute("enabled")


@pytest.mark.pyjs_python
def test_state_assignment_after_dom_initialization_overrides_default():
    element = InitializedState()

    assert element.title == "Chosen"
    assert element.getAttribute("title") == "Chosen"


@pytest.mark.pyjs_python
def test_custom_elements_can_be_appended_to_referenced_containers():
    parent = ReactiveCounter()
    child = ReactiveCounter()

    parent.output.append(child)

    assert child.parentNode is parent.output
    assert child.parentElement is parent.output


@pytest.mark.pyjs_python
def test_effect_dependencies_are_validated():
    with pytest.raises(TypeError, match="fields declared with state"):
        effect("missing")

    with pytest.raises(TypeError, match="from another class"):

        class InvalidElement(CustomElement):
            @effect(ReactiveCounter.count)
            def update(self):
                pass


@pytest.mark.pyjs_python
def test_mutable_state_defaults_are_rejected():
    with pytest.raises(TypeError, match="str, int, float, or bool"):
        state([])
