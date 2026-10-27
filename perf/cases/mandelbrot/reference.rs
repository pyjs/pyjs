fn kernel(size: i64) -> i64 {
    let mut checksum = 0;
    for y in 0..size {
        let ci = y as f64 * 2.0 / size as f64 - 1.0;
        for x in 0..size {
            let cr = x as f64 * 2.0 / size as f64 - 1.5;
            let mut zr = 0.0;
            let mut zi = 0.0;
            let mut count = 0;
            while count < 50 && zr * zr + zi * zi <= 4.0 {
                let next_real = zr * zr - zi * zi + cr;
                zi = 2.0 * zr * zi + ci;
                zr = next_real;
                count += 1;
            }
            checksum += (y * size + x + 1) * count;
        }
    }
    checksum
}
