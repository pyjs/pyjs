use std::collections::HashMap;
fn kernel(size: i64) -> i64 {
    let mut counts: HashMap<i64, i64> = HashMap::new();
    for i in 0..size {
        let key = i * 17 % 257;
        let count = counts.get(&key).copied().unwrap_or(0);
        counts.insert(key, count + 1);
    }
    let mut checksum = 0;
    for key in counts.keys() { checksum += (key + 1) * counts[key]; }
    checksum
}
