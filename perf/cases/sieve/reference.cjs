function kernel(size) {
    const flags = [];
    for (let i = 0; i < size + 1; i++) flags.push(1);
    let p = 2;
    while (p * p <= size) {
        if (flags[p] === 1) {
            let multiple = p * p;
            while (multiple <= size) {
                flags[multiple] = 0;
                multiple += p;
            }
        }
        p++;
    }
    let count = 0;
    for (let i = 2; i < size + 1; i++) count += flags[i];
    return count;
}
