"""Stable sorting through the JVM's existing generic-class specialization."""

from collections.abc import Callable


class Sorted[Source, Item]:
    """O(n log n) comparisons, O(n) auxiliary storage, and bounded stack depth.

    Only < is used; equal entries retain their order in both directions. Input
    iteration completes before comparison and never mutates the input itself.
    """

    def __init__(self, source: Source, reverse: bool = False):
        values: list[Item] = []
        for value in source:
            values.append(value)
        output = values.copy()
        count = len(values)
        width = 1
        while width < count:
            start = 0
            while start < count:
                middle = min(start + width, count)
                end = min(middle + width, count)
                left = start
                right = middle
                index = start
                while index < end:
                    take_right = left == middle
                    if left < middle and right < end:
                        take_right = values[left] < values[right] if reverse else values[right] < values[left]
                    if right < end and take_right:
                        output[index] = values[right]
                        right += 1
                    else:
                        output[index] = values[left]
                        left += 1
                    index += 1
                start = end
            previous = values
            values = output
            output = previous
            width *= 2
        self.result = values


class SortEntry[Item, Key]:
    def __init__(self, value: Item, key: Key):
        self.value = value
        self.key = key

    def __lt__(self, other: SortEntry[Item, Key]) -> bool:
        return self.key < other.key


class KeyedSorted[Source, Item, Key]:
    def __init__(self, source: Source, key: Callable[[Item], Key], reverse: bool = False):
        values: list[Item] = []
        for value in source:
            values.append(value)
        decorated: list[SortEntry[Item, Key]] = []
        for value in values:
            decorated.append(SortEntry[Item, Key](value, key(value)))
        ordered = Sorted[list[SortEntry[Item, Key]], SortEntry[Item, Key]](decorated, reverse)
        result: list[Item] = []
        for entry in ordered.result:
            result.append(entry.value)
        self.result = result
