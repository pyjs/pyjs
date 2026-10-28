fn element(i: usize, j: usize) -> f64 { 1.0 / (((i + j) * (i + j + 1) / 2 + i + 1) as f64) }
fn multiply(source: &[f64], result: &mut [f64], size: usize, transpose: bool) {
    for i in 0..size {
        let mut total = 0.0;
        for j in 0..size {
            if transpose { total += element(j, i) * source[j]; }
            else { total += element(i, j) * source[j]; }
        }
        result[i] = total;
    }
}
fn kernel(size: i64) -> i64 {
    if size == 0 { return 0; }
    let size = size as usize;
    let mut u = Vec::new(); let mut v = Vec::new(); let mut temporary = Vec::new();
    for _ in 0..size { u.push(1.0); v.push(0.0); temporary.push(0.0); }
    for _ in 0..10 {
        multiply(&u, &mut temporary, size, false); multiply(&temporary, &mut v, size, true);
        multiply(&v, &mut temporary, size, false); multiply(&temporary, &mut u, size, true);
    }
    let mut numerator = 0.0; let mut denominator = 0.0;
    for i in 0..size { numerator += u[i] * v[i]; denominator += v[i] * v[i]; }
    ((numerator / denominator).sqrt() * 1000000000.0) as i64
}
