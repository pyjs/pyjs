from pyjs import js


def compile_pattern(pattern):
    if not isinstance(pattern, str):
        raise TypeError("Client model patterns must be strings, not compiled regular expressions")
    if len(pattern) > 4096:
        raise TypeError("Client model pattern exceeds 4096 characters")
    start = pattern.startswith("^")
    index = int(start)
    end = False
    program = []

    def unsupported():
        raise TypeError(
            "Unsupported client model pattern; use literals, character ranges, "
            "dot, repetitions, and outer ^/$ anchors without groups, "
            "alternation, flags, Unicode classes, or class set operations"
        )

    def character(in_class=False):
        nonlocal index
        if index >= len(pattern):
            unsupported()
        value = pattern[index]
        index += 1
        if value == "\\":
            if index >= len(pattern):
                unsupported()
            value = pattern[index]
            index += 1
            if value in "nrt":
                return {"n": "\n", "r": "\r", "t": "\t"}[value]
            if value not in r"\.^$|?*+()[]{}-":
                unsupported()
        elif value in ("[]&~-" if in_class else ".^$|?*+()[]{}"):
            unsupported()
        if 0xD800 <= ord(value) <= 0xDFFF:
            unsupported()
        return value

    while index < len(pattern):
        if pattern[index] == "$" and index == len(pattern) - 1:
            end = True
            break
        negate = False
        ranges = []
        if pattern[index] == "[":
            index += 1
            if index < len(pattern) and pattern[index] == "^":
                negate = True
                index += 1
            while index < len(pattern) and pattern[index] != "]":
                low = character(True)
                high = low
                if index < len(pattern) and pattern[index] == "-":
                    index += 1
                    high = character(True)
                if ord(low) > ord(high):
                    unsupported()
                ranges.extend((ord(low), ord(high)))
            if not ranges or index >= len(pattern):
                unsupported()
            index += 1
        elif pattern[index] == ".":
            negate, ranges = True, [10, 10]
            index += 1
        else:
            value = character()
            ranges = [ord(value), ord(value)]
        minimum = maximum = 1
        if index < len(pattern) and pattern[index] in "?*+":
            quantifier = pattern[index]
            index += 1
            minimum = int(quantifier == "+")
            maximum = 1 if quantifier == "?" else -1
        elif index < len(pattern) and pattern[index] == "{":
            close = pattern.find("}", index)
            if close < 0:
                unsupported()
            bounds = pattern[index + 1:close].split(",")
            if (len(bounds) not in (1, 2) or not bounds[0]
                    or any(character not in "0123456789," for character in pattern[index + 1:close])
                    or any(len(bound) > 3 for bound in bounds)):
                unsupported()
            minimum = int(bounds[0])
            maximum = minimum if len(bounds) == 1 else int(bounds[1]) if bounds[1] else -1
            if maximum != -1 and maximum < minimum:
                unsupported()
            index = close + 1
        count = minimum + 1 if maximum == -1 else maximum
        if len(program) + count > 256:
            raise TypeError("Client model pattern exceeds 256 matching states")
        for position in range(count):
            program.append([int(position >= minimum),
                            int(maximum == -1 and position == minimum),
                            int(negate), *ranges])
    return [[int(start), int(end)], *program]


@js
def matches_pattern(value: str, program: list[list[int]]) -> bool:
    # Parallel states prevent backtracking on overlapping repetitions. The
    # compiler bounds the program; storage does not grow with the input.
    count = len(program) - 1
    # Header: start/end anchors. Each state: optional/repeat/negate flags,
    # then inclusive code-point range pairs.
    anchored_start = program[0][0] == 1
    anchored_end = program[0][1] == 1
    active: list[bool] = []
    following: list[bool] = []
    for _ in range(count + 1):
        active.append(False)
        following.append(False)
    active[0] = True
    for index in range(count):
        if active[index] and program[index + 1][0] == 1:
            active[index + 1] = True
    if active[count] and not anchored_end:
        return True
    for character in value:
        point = ord(character)
        reachable = False
        for index in range(count + 1):
            following[index] = False
        for index in range(count):
            if active[index]:
                atom = program[index + 1]
                included = False
                for offset in range(3, len(atom), 2):
                    if atom[offset] <= point <= atom[offset + 1]:
                        included = True
                        break
                if included != (atom[2] == 1):
                    target = index if atom[1] == 1 else index + 1
                    following[target] = True
                    reachable = True
        if anchored_start and not reachable:
            return False
        if not anchored_start:
            following[0] = True
        for index in range(count):
            if following[index] and program[index + 1][0] == 1:
                following[index + 1] = True
        previous = active
        active = following
        following = previous
        if active[count] and not anchored_end:
            return True
    return active[count]
