function element(i, j) { return 1.0 / (Math.floor((i + j) * (i + j + 1) / 2) + i + 1); }
function multiply(source, result, size, transpose) {
    for (let i = 0; i < size; i++) {
        let total = 0.0;
        for (let j = 0; j < size; j++) {
            if (transpose) total += element(j, i) * source[j];
            else total += element(i, j) * source[j];
        }
        result[i] = total;
    }
}
function kernel(size) {
    if (size === 0) return 0;
    const u = [], v = [], temporary = [];
    for (let i = 0; i < size; i++) { u.push(1.0); v.push(0.0); temporary.push(0.0); }
    for (let step = 0; step < 10; step++) {
        multiply(u, temporary, size, false); multiply(temporary, v, size, true);
        multiply(v, temporary, size, false); multiply(temporary, u, size, true);
    }
    let numerator = 0.0, denominator = 0.0;
    for (let i = 0; i < size; i++) { numerator += u[i] * v[i]; denominator += v[i] * v[i]; }
    return Math.trunc(Math.sqrt(numerator / denominator) * 1000000000.0);
}
