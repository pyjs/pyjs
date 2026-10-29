struct Record { value: i64, weight: i64 }
impl Record {
    fn new(value: i64) -> Self { Self { value, weight: value % 7 } }
    fn score(&self) -> i64 { self.value * self.weight }
}
fn kernel(size: i64) -> i64 {
    // Box preserves individually allocated objects, rather than a packed struct array.
    let mut records: Vec<Box<Record>> = Vec::new();
    for i in 0..size { records.push(Box::new(Record::new(i))); }
    let mut checksum = 0;
    for record in &records { checksum += record.score(); }
    checksum
}
