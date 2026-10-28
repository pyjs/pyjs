def visit(items: list[int], start: int, size: int) -> int:
    if start == size:
        score = 0
        for i in range(size):
            score += (i + 1) * items[i]
        return score
    checksum = 0
    for i in range(start, size):
        saved = items[start]
        items[start] = items[i]
        items[i] = saved
        checksum += visit(items, start + 1, size)
        saved = items[start]
        items[start] = items[i]
        items[i] = saved
    return checksum


def kernel(size: int) -> int:
    items: list[int] = []
    for i in range(size):
        items.append(i + 1)
    return visit(items, 0, size)
