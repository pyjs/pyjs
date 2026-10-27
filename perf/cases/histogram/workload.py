def kernel(size: int) -> int:
    counts: dict[int, int] = {}
    for i in range(size):
        key = i * 17 % 257
        counts[key] = counts.get(key, 0) + 1
    checksum = 0
    for key in counts:
        checksum += (key + 1) * counts[key]
    return checksum
