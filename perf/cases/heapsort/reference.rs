fn sift(values: &mut [i64], mut root: usize, end: usize) {
    while root * 2 + 1 < end {
        let mut child = root * 2 + 1;
        if child + 1 < end && values[child] < values[child + 1] { child += 1; }
        if values[root] >= values[child] { return; }
        let saved = values[root]; values[root] = values[child]; values[child] = saved;
        root = child;
    }
}
fn kernel(size: i64) -> i64 {
    let mut values: Vec<i64> = Vec::new();
    for i in 0..size { values.push((i * 73 + 19) % 1009 - 504); }
    for root in (0..size as usize / 2).rev() { sift(&mut values, root, size as usize); }
    for end in (1..size as usize).rev() {
        let saved = values[0]; values[0] = values[end]; values[end] = saved;
        sift(&mut values, 0, end);
    }
    let mut checksum = 0;
    for i in 0..size as usize { checksum += (i as i64 + 1) * values[i]; }
    checksum
}
