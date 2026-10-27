public final class Kernel {
    public static long kernel(long size) {
        long[] flags = new long[(int)size + 1];
        for (int i = 0; i <= size; i++) flags[i] = 1;
        long p = 2;
        while (p * p <= size) {
            if (flags[(int)p] == 1) {
                long multiple = p * p;
                while (multiple <= size) {
                    flags[(int)multiple] = 0;
                    multiple += p;
                }
            }
            p++;
        }
        long count = 0;
        for (long i = 2; i <= size; i++) count += flags[(int)i];
        return count;
    }
}
