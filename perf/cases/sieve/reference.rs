fn kernel(size: i64) -> i64 {
    let mut flags: Vec<i64> = Vec::new();
    for _ in 0..=size { flags.push(1); }
    let mut p = 2;
    while p * p <= size {
        if flags[p as usize] == 1 {
            let mut multiple = p * p;
            while multiple <= size {
                flags[multiple as usize] = 0;
                multiple += p;
            }
        }
        p += 1;
    }
    let mut count = 0;
    for i in 2..=size { count += flags[i as usize]; }
    count
}
