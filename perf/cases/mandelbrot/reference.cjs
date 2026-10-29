function kernel(size) {
    let checksum = 0;
    for (let y = 0; y < size; y++) {
        const ci = y * 2.0 / size - 1.0;
        for (let x = 0; x < size; x++) {
            const cr = x * 2.0 / size - 1.5;
            let zr = 0.0, zi = 0.0, count = 0;
            while (count < 50 && zr * zr + zi * zi <= 4.0) {
                const nextReal = zr * zr - zi * zi + cr;
                zi = 2.0 * zr * zi + ci;
                zr = nextReal;
                count++;
            }
            checksum += (y * size + x + 1) * count;
        }
    }
    return checksum;
}
