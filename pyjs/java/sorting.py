"""Stable sorting through the JVM's existing generic-class specialization."""


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
