"""Small typed source fixture for iterator-view boundary matrices."""

import textwrap


def generator_view(actual: str, expected: str, *, slot: str) -> str:
    """Define values(payload) and view(source); the caller supplies main().

    actual -> expected is the value conversion, reversed in the generator's
    send annotation. Passing payload through a typed parameter keeps literal
    inference from replacing the union being tested. No tests run implicitly.
    """
    source, target = ['int', 'None', 'None'], ['int', 'None', 'None']
    index = {'yield': 0, 'send': 1, 'completion': 2}[slot]
    source[index], target[index] = (expected, actual) if slot == 'send' else (actual, expected)
    if slot == 'yield':
        body = 'yield payload'
    elif slot == 'send':
        source[2] = target[2] = 'str'
        body = 'received = yield 0\nreturn repr(received)'
    else:
        body = 'try:\n    yield 1\nexcept GeneratorExit:\n    return payload\nreturn payload'
    return ('from collections.abc import Generator\n'
            f'def values(payload: {actual}) -> Generator[{", ".join(source)}]:\n'
            f'{textwrap.indent(body, "    ")}\n'
            f'def view(source: Generator[{", ".join(source)}]) -> Generator[{", ".join(target)}]:\n'
            '    return source\n')
