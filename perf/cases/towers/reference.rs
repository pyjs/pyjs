fn move_disks(piles: &mut [Vec<i64>], count: i64, source: usize, destination: usize) -> i64 {
    if count == 0 { return 0; }
    let other = 3 - source - destination;
    let mut moves = move_disks(piles, count - 1, source, other);
    let disk = piles[source].pop().unwrap();
    piles[destination].push(disk);
    moves += 1;
    moves + move_disks(piles, count - 1, other, destination)
}
fn kernel(size: i64) -> i64 {
    let mut first = Vec::new();
    for i in 0..size { first.push(size - i); }
    let mut piles = vec![first, Vec::new(), Vec::new()];
    let mut checksum = move_disks(&mut piles, size, 0, 2);
    if !piles[0].is_empty() || !piles[1].is_empty() || piles[2].len() != size as usize { return -1; }
    for i in 0..size as usize {
        if piles[2][i] != size - i as i64 { return -1; }
        checksum += (i as i64 + 1) * piles[2][i];
    }
    checksum
}
