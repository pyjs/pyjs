function move(piles, count, source, destination) {
    if (count === 0) return 0;
    const other = 3 - source - destination;
    let moves = move(piles, count - 1, source, other);
    const disk = piles[source].pop();
    piles[destination].push(disk);
    moves++;
    return moves + move(piles, count - 1, other, destination);
}
function kernel(size) {
    const first = [], second = [], third = [];
    for (let i = 0; i < size; i++) first.push(size - i);
    const piles = [first, second, third];
    let checksum = move(piles, size, 0, 2);
    if (first.length !== 0 || second.length !== 0 || third.length !== size) return -1;
    for (let i = 0; i < size; i++) {
        if (third[i] !== size - i) return -1;
        checksum += (i + 1) * third[i];
    }
    return checksum;
}
