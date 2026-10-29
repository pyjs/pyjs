fn kernel(size: i64) -> i64 {
    let mut left: Vec<i64> = Vec::new();
    let mut right: Vec<i64> = Vec::new();
    let mut output: Vec<i64> = Vec::new();
    for i in 0..size * size {
        left.push(i % 17); right.push(i % 13); output.push(0);
    }
    for row in 0..size {
        for col in 0..size {
            let mut total = 0;
            for k in 0..size {
                total += left[(row * size + k) as usize] * right[(k * size + col) as usize];
            }
            output[(row * size + col) as usize] = total;
        }
    }
    output.iter().sum()
}
