import math


def element(i: int, j: int) -> float:
    return 1.0 / ((i + j) * (i + j + 1) // 2 + i + 1)


def multiply(source: list[float], result: list[float], size: int, transpose: bool) -> None:
    for i in range(size):
        total = 0.0
        for j in range(size):
            if transpose:
                total += element(j, i) * source[j]
            else:
                total += element(i, j) * source[j]
        result[i] = total


def kernel(size: int) -> int:
    if size == 0:
        return 0
    u: list[float] = []
    v: list[float] = []
    temporary: list[float] = []
    for _ in range(size):
        u.append(1.0)
        v.append(0.0)
        temporary.append(0.0)
    for _ in range(10):
        multiply(u, temporary, size, False)
        multiply(temporary, v, size, True)
        multiply(v, temporary, size, False)
        multiply(temporary, u, size, True)
    numerator = 0.0
    denominator = 0.0
    for i in range(size):
        numerator += u[i] * v[i]
        denominator += v[i] * v[i]
    return int(math.sqrt(numerator / denominator) * 1000000000.0)
