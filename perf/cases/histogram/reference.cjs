function kernel(size) {
    const counts = new Map();
    for (let i = 0; i < size; i++) {
        const key = i * 17 % 257;
        counts.set(key, (counts.get(key) || 0) + 1);
    }
    let checksum = 0;
    for (const key of counts.keys()) checksum += (key + 1) * counts.get(key);
    return checksum;
}
