def search(board: list[int], row: int, size: int) -> int:
    if row == size:
        return 1
    total = 0
    for col in range(size):
        valid = True
        for previous in range(row):
            distance = board[previous] - col
            if distance == 0 or distance == row - previous or distance == previous - row:
                valid = False
                break
        if valid:
            board[row] = col
            total += search(board, row + 1, size)
    return total


def kernel(size: int) -> int:
    board: list[int] = []
    for _ in range(size):
        board.append(0)
    return search(board, 0, size)
