from pyjs_examples.nativescript_counter.counter import Counter


def test_counter_updates_label():
    counter = Counter()

    counter.increment(None)
    counter.increment(None)

    assert counter.count == 2
    assert counter.value.text == "2"
