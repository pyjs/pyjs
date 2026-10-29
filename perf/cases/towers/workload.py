def move(piles: list[list[int]], count: int, source: int, destination: int) -> int:
    if count == 0:
        return 0
    other = 3 - source - destination
    moves = move(piles, count - 1, source, other)
    disk = piles[source].pop()
    piles[destination].append(disk)
    moves += 1
    return moves + move(piles, count - 1, other, destination)


def kernel(size: int) -> int:
    first: list[int] = []
    second: list[int] = []
    third: list[int] = []
    for i in range(size):
        first.append(size - i)
    piles = [first, second, third]
    checksum = move(piles, size, 0, 2)
    if len(first) != 0 or len(second) != 0 or len(third) != size:
        return -1
    for i in range(size):
        if third[i] != size - i:
            return -1
        checksum += (i + 1) * third[i]
    return checksum
