def kernel(size: int) -> int:
    flags: list[int] = []
    for _i in range(size + 1):
        flags.append(1)
    p = 2
    while p * p <= size:
        if flags[p] == 1:
            multiple = p * p
            while multiple <= size:
                flags[multiple] = 0
                multiple += p
        p += 1
    count = 0
    for i in range(2, size + 1):
        count += flags[i]
    return count
