def kernel(size: int) -> int:
    checksum = 0
    for y in range(size):
        ci = y * 2.0 / size - 1.0
        for x in range(size):
            cr = x * 2.0 / size - 1.5
            zr = 0.0
            zi = 0.0
            count = 0
            while count < 50 and zr * zr + zi * zi <= 4.0:
                next_real = zr * zr - zi * zi + cr
                zi = 2.0 * zr * zi + ci
                zr = next_real
                count += 1
            checksum += (y * size + x + 1) * count
    return checksum
