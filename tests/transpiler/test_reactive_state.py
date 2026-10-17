from pyjs import effect, js, state
from pyjs.analysis.analyzer import release_compilation
from pyjs.javascript.transpiler import prepare_bundle
from pyjs.web.domx import CustomElement, ref, span, tag


@js
class TranspiledCounter(CustomElement):
    count = state(1)

    def __init__(self):
        super().__init__()
        self.output = ref(span())
        tag(self, self.output)

    @effect(count)
    def render_count(self):
        self.output.textContent = str(self.count)

    def increment(self):
        self.count += 1


def reactive_entry_point():
    counter = TranspiledCounter()
    counter.increment()


def test_state_declarations_generate_observed_properties_and_effects():
    package, entry_point, _ = prepare_bundle(reactive_entry_point, include_css=False)
    source = package[__name__]
    release_compilation(entry_point)

    assert "pyjs.state" not in package
    assert 'Object.defineProperty(TranspiledCounter.prototype, "count"' in source
    assert "TranspiledCounter.observedAttributes = ['count'];" in source
    assert "var $assignment2 = this;" in source
    assert "$assignment2.count = $assignment2.count + 1;" in source
    assert "this.render_count();" in source
