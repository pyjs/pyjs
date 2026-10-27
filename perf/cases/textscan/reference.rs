fn kernel(size: i64) -> i64 {
    let text = "aé😀z".repeat(size as usize);
    let mut checksum = 0;
    for character in text.chars() {
        checksum += match character { 'a' => 1, 'é' => 2, '😀' => 3, _ => 4 };
    }
    checksum
}
