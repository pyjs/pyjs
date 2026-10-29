function search(board, row, size) {
    if (row === size) return 1;
    let total = 0;
    for (let col = 0; col < size; col++) {
        let valid = true;
        for (let previous = 0; previous < row; previous++) {
            const distance = board[previous] - col;
            if (distance === 0 || distance === row - previous || distance === previous - row) {
                valid = false;
                break;
            }
        }
        if (valid) {
            board[row] = col;
            total += search(board, row + 1, size);
        }
    }
    return total;
}
function kernel(size) {
    const board = [];
    for (let i = 0; i < size; i++) board.push(0);
    return search(board, 0, size);
}
