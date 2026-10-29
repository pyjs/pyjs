fn search(board: &mut [i64], row: usize, size: usize) -> i64 {
    if row == size { return 1; }
    let mut total = 0;
    for col in 0..size {
        let mut valid = true;
        for previous in 0..row {
            let distance = board[previous] - col as i64;
            if distance == 0 || distance == (row - previous) as i64 || distance == previous as i64 - row as i64 {
                valid = false;
                break;
            }
        }
        if valid {
            board[row] = col as i64;
            total += search(board, row + 1, size);
        }
    }
    total
}
fn kernel(size: i64) -> i64 {
    let mut board = Vec::new();
    for _ in 0..size { board.push(0); }
    search(&mut board, 0, size as usize)
}
