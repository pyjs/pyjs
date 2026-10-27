public final class Kernel {
    static void sift(long[] values, int root, int end) {
        while (root * 2 + 1 < end) {
            int child = root * 2 + 1;
            if (child + 1 < end && values[child] < values[child + 1]) child++;
            if (values[root] >= values[child]) return;
            long saved = values[root]; values[root] = values[child]; values[child] = saved;
            root = child;
        }
    }
    public static long kernel(long size) {
        long[] values = new long[(int)size];
        for (int i = 0; i < size; i++) values[i] = (i * 73L + 19) % 1009 - 504;
        for (int root = (int)size / 2 - 1; root >= 0; root--) sift(values, root, (int)size);
        for (int end = (int)size - 1; end > 0; end--) {
            long saved = values[0]; values[0] = values[end]; values[end] = saved;
            sift(values, 0, end);
        }
        long checksum = 0;
        for (int i = 0; i < size; i++) checksum += (i + 1L) * values[i];
        return checksum;
    }
}
