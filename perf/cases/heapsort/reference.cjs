function sift(values, root, end) {
    while (root * 2 + 1 < end) {
        let child = root * 2 + 1;
        if (child + 1 < end && values[child] < values[child + 1]) child++;
        if (values[root] >= values[child]) return;
        const saved = values[root]; values[root] = values[child]; values[child] = saved;
        root = child;
    }
}
function kernel(size) {
    const values = [];
    for (let i = 0; i < size; i++) values.push((i * 73 + 19) % 1009 - 504);
    for (let root = Math.floor(size / 2) - 1; root >= 0; root--) sift(values, root, size);
    for (let end = size - 1; end > 0; end--) {
        const saved = values[0]; values[0] = values[end]; values[end] = saved;
        sift(values, 0, end);
    }
    let checksum = 0;
    for (let i = 0; i < size; i++) checksum += (i + 1) * values[i];
    return checksum;
}
