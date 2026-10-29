public final class Kernel {
    static long search(long[] board, int row, int size) {
        if (row == size) return 1;
        long total = 0;
        for (int col = 0; col < size; col++) {
            boolean valid = true;
            for (int previous = 0; previous < row; previous++) {
                long distance = board[previous] - col;
                if (distance == 0 || distance == row - previous || distance == previous - row) {
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
    public static long kernel(long size) {
        return search(new long[(int) size], 0, (int) size);
    }
}
