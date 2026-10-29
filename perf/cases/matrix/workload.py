def kernel(size: int) -> int:
    left: list[int] = []
    right: list[int] = []
    output: list[int] = []
    for i in range(size * size):
        left.append(i % 17)
        right.append(i % 13)
        output.append(0)
    for row in range(size):
        for col in range(size):
            total = 0
            for k in range(size):
                total += left[row * size + k] * right[k * size + col]
            output[row * size + col] = total
    checksum = 0
    for i in range(size * size):
        checksum += output[i]
    return checksum
