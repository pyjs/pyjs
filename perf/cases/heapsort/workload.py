def sift(values: list[int], root: int, end: int) -> None:
    while root * 2 + 1 < end:
        child = root * 2 + 1
        if child + 1 < end and values[child] < values[child + 1]:
            child += 1
        if values[root] >= values[child]:
            return
        saved = values[root]
        values[root] = values[child]
        values[child] = saved
        root = child


def kernel(size: int) -> int:
    values: list[int] = []
    for i in range(size):
        values.append((i * 73 + 19) % 1009 - 504)
    for root in range(size // 2 - 1, -1, -1):
        sift(values, root, size)
    for end in range(size - 1, 0, -1):
        saved = values[0]
        values[0] = values[end]
        values[end] = saved
        sift(values, 0, end)
    checksum = 0
    for i in range(size):
        checksum += (i + 1) * values[i]
    return checksum
