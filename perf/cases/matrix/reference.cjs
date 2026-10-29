function kernel(size) {
    const left = [], right = [], output = [];
    for (let i = 0; i < size * size; i++) {
        left.push(i % 17);
        right.push(i % 13);
        output.push(0);
    }
    for (let row = 0; row < size; row++) {
        for (let col = 0; col < size; col++) {
            let total = 0;
            for (let k = 0; k < size; k++) {
                total += left[row * size + k] * right[k * size + col];
            }
            output[row * size + col] = total;
        }
    }
    let checksum = 0;
    for (let i = 0; i < size * size; i++) checksum += output[i];
    return checksum;
}
