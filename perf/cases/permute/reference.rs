fn visit(items: &mut [i64], start: usize, size: usize) -> i64 {
    if start == size {
        let mut score = 0;
        for i in 0..size { score += (i as i64 + 1) * items[i]; }
        return score;
    }
    let mut checksum = 0;
    for i in start..size {
        items.swap(start, i);
        checksum += visit(items, start + 1, size);
        items.swap(start, i);
    }
    checksum
}
fn kernel(size: i64) -> i64 {
    let mut items = Vec::new();
    for i in 0..size { items.push(i + 1); }
    visit(&mut items, 0, size as usize)
}
