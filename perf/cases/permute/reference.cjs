function visit(items, start, size) {
    if (start === size) {
        let score = 0;
        for (let i = 0; i < size; i++) score += (i + 1) * items[i];
        return score;
    }
    let checksum = 0;
    for (let i = start; i < size; i++) {
        let saved = items[start]; items[start] = items[i]; items[i] = saved;
        checksum += visit(items, start + 1, size);
        saved = items[start]; items[start] = items[i]; items[i] = saved;
    }
    return checksum;
}
function kernel(size) {
    const items = [];
    for (let i = 0; i < size; i++) items.push(i + 1);
    return visit(items, 0, size);
}
