fn batch(size: i64, loops: i64) -> String {
    let mut checksum = 0;
    for i in 0..loops {
        checksum += kernel(std::hint::black_box(size + i % 2));
    }
    checksum.to_string()
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let size: i64 = args[1].parse().unwrap();
    let loops: i64 = args[2].parse().unwrap();
    let warmups: usize = args[3].parse().unwrap();
    let samples: usize = args[4].parse().unwrap();
    for i in 0..warmups + samples {
        let start = std::time::Instant::now();
        let result = batch(size, loops);
        let elapsed = start.elapsed().as_nanos();
        println!("{} {} {}", if i < warmups { "warmup" } else { "sample" }, result, elapsed);
    }
}
