public final class Kernel {
    static long visit(long[] items, int start, int size) {
        if (start == size) {
            long score = 0;
            for (int i = 0; i < size; i++) score += (i + 1) * items[i];
            return score;
        }
        long checksum = 0;
        for (int i = start; i < size; i++) {
            long saved = items[start]; items[start] = items[i]; items[i] = saved;
            checksum += visit(items, start + 1, size);
            saved = items[start]; items[start] = items[i]; items[i] = saved;
        }
        return checksum;
    }
    public static long kernel(long size) {
        long[] items = new long[(int) size];
        for (int i = 0; i < size; i++) items[i] = i + 1;
        return visit(items, 0, (int) size);
    }
}
