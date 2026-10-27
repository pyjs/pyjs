"""Operand-stack slot analysis for the class-file subset emitted by PyJS.

This computes Code.max_stack, not verifier types or StackMapTable frames.
Longs/doubles occupy two slots; exception entries start with one reference.
Unknown instructions fail closed rather than guessing an unsafe capacity.
"""

from pyjs.java.classpath import parse_jvm_method_descriptor


def descriptor_slots(descriptor: str) -> tuple[int, int]:
    """Return parameter/result widths (or (0, width) for a field)."""
    parameters, result = parse_jvm_method_descriptor(
        descriptor if descriptor.startswith("(") else "()" + descriptor
    )
    arguments = sum(2 if item in {"J", "D"} else 1 for item in parameters)
    return arguments, 0 if result == "V" else 2 if result in {"J", "D"} else 1


# JVMS 6.5: opcode -> (encoded length, popped slots, pushed slots).
# Constants, including the two-slot long/double constants.
_OPS = {0x00: (1, 0, 0)}
for _op in range(0x01, 0x10):
    _OPS[_op] = (1, 0, 2 if _op in {0x09, 0x0A, 0x0E, 0x0F} else 1)
_OPS.update({0x10: (2, 0, 1), 0x11: (3, 0, 1), 0x12: (2, 0, 1),
             0x13: (3, 0, 1), 0x14: (3, 0, 2)})
# Typed local loads/stores and their compact _0 ... _3 forms.
for _kind, _width in enumerate((1, 2, 1, 2, 1)):
    _OPS[0x15 + _kind] = (2, 0, _width)
    _OPS[0x36 + _kind] = (2, _width, 0)
    for _offset in range(4):
        _OPS[0x1A + 4 * _kind + _offset] = (1, 0, _width)
        _OPS[0x3B + 4 * _kind + _offset] = (1, _width, 0)
# Array access consumes a reference and an int index.
for _kind, _width in enumerate((1, 2, 1, 2, 1, 1, 1, 1)):
    _OPS[0x2E + _kind] = (1, 2, _width)
    _OPS[0x4F + _kind] = (1, 2 + _width, 0)
# pop/dup/swap variants have fixed slot effects across their legal type forms.
for _op, (_pop, _push) in enumerate(((1, 0), (2, 0), (1, 2), (2, 3),
                                    (3, 4), (2, 4), (3, 5), (4, 6), (2, 2)), 0x57):
    _OPS[_op] = (1, _pop, _push)
# Arithmetic, shifts/bitwise operations, then scalar conversions/comparisons.
for _op in range(0x60, 0x78):
    _width = (1, 2, 1, 2)[_op % 4]
    _OPS[_op] = (1, _width * (2 if _op < 0x74 else 1), _width)
for _op in range(0x78, 0x84):
    _width = 1 + _op % 2
    _OPS[_op] = (1, _width + (1 if _op < 0x7E else _width), _width)
_OPS[0x84] = (3, 0, 0)
for _op, (_pop, _push) in enumerate(((1, 2), (1, 1), (1, 2), (2, 1), (2, 1), (2, 2),
                                    (1, 1), (1, 2), (1, 2), (2, 1), (2, 2), (2, 1),
                                    (1, 1), (1, 1), (1, 1)), 0x85):
    _OPS[_op] = (1, _pop, _push)
for _op in range(0x94, 0x99):
    _OPS[_op] = (1, 2 if _op in {0x95, 0x96} else 4, 1)
for _op in range(0x99, 0xA7):
    _OPS[_op] = (3, 1 if _op < 0x9F else 2, 0)
_OPS.update({0xA7: (3, 0, 0), 0xC6: (3, 1, 0), 0xC7: (3, 1, 0), 0xC8: (5, 0, 0)})
for _op, _width in enumerate((1, 2, 1, 2, 1, 0), 0xAC):
    _OPS[_op] = (1, _width, 0)
_OPS.update({0xBB: (3, 0, 1), 0xBC: (2, 1, 1), 0xBD: (3, 1, 1),
             0xBE: (1, 1, 1), 0xBF: (1, 1, 0), 0xC0: (3, 1, 1),
             0xC1: (3, 1, 1), 0xC2: (1, 1, 0), 0xC3: (1, 1, 0)})


def stack_bound(code: bytes, descriptors: dict[int, str], handlers=()) -> int:
    """Propagate stack heights through branches, backedges and handler entries."""
    instructions = {}
    position = 0
    while position < len(code):
        opcode = code[position]
        if 0xB2 <= opcode <= 0xB9:
            if position + 3 > len(code):
                raise ValueError("truncated JVM instruction")
            reference = int.from_bytes(code[position + 1:position + 3], "big")
            arguments, result = descriptor_slots(descriptors[reference])
            if opcode <= 0xB5:
                pop = (result if opcode in {0xB3, 0xB5} else 0) + (opcode >= 0xB4)
                push = result if opcode in {0xB2, 0xB4} else 0
            else:
                pop, push = arguments + (opcode != 0xB8), result
            length = 5 if opcode == 0xB9 else 3
        elif opcode == 0xC4:
            if position + 2 > len(code):
                raise ValueError("truncated JVM instruction")
            nested = code[position + 1]
            if nested not in {*range(0x15, 0x1A), *range(0x36, 0x3B), 0x84}:
                raise ValueError(f"unsupported wide JVM instruction: {nested:#x}")
            _, pop, push = _OPS[nested]
            length = 6 if nested == 0x84 else 4
        elif opcode in _OPS:
            length, pop, push = _OPS[opcode]
        else:
            raise ValueError(f"unsupported JVM stack-analysis instruction: {opcode:#x}")
        end = position + length
        if end > len(code):
            raise ValueError("truncated JVM instruction")
        successors = [] if opcode in {*range(0xAC, 0xB2), 0xBF} else [end]
        if 0x99 <= opcode <= 0xA7 or opcode in {0xC6, 0xC7, 0xC8}:
            offset = int.from_bytes(code[position + 1:end], "big", signed=True)
            successors = ([] if opcode in {0xA7, 0xC8} else [end]) + [position + offset]
        instructions[position] = (pop, push, successors)
        position = end
    pending = [(0, 0), *[(handler.handler, 1) for handler in handlers]]
    heights = {}
    maximum = 0
    while pending:
        position, height = pending.pop()
        if position in heights:
            if heights[position] != height:
                raise ValueError(f"inconsistent JVM stack height at byte {position}")
            continue
        if position not in instructions:
            raise ValueError(f"invalid JVM control-flow target: {position}")
        heights[position] = height
        pop, push, successors = instructions[position]
        if height < pop:
            raise ValueError(f"JVM operand stack underflow at byte {position}")
        after = height - pop + push
        maximum = max(maximum, height, after)
        if maximum > 65535:
            raise ValueError("JVM operand stack exceeds 65535 slots")
        pending.extend((target, after) for target in successors)
    return maximum
