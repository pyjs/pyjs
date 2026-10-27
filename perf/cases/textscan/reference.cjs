function kernel(size) {
    const text = "aé😀z".repeat(size);
    let checksum = 0;
    for (const character of text) {
        if (character === "a") checksum++;
        else if (character === "é") checksum += 2;
        else if (character === "😀") checksum += 3;
        else checksum += 4;
    }
    return checksum;
}
