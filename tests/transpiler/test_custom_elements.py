from pyjs.web.domx import CustomElement


def test_single_word_custom_element_names_receive_a_valid_prefix():
    class Counter(CustomElement):
        pass

    class CounterApp(CustomElement):
        pass

    assert Counter.localName == "pyjs-counter"
    assert Counter.tagName == "PYJS-COUNTER"
    assert CounterApp.localName == "counter-app"
    assert CounterApp.tagName == "COUNTER-APP"
