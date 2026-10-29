public final class Kernel {
    public static long kernel(long size) {
        long[] left = new long[(int)(size * size)];
        long[] right = new long[left.length];
        long[] output = new long[left.length];
        for (int i = 0; i < left.length; i++) {
            left[i] = i % 17; right[i] = i % 13;
        }
        for (long row = 0; row < size; row++) {
            for (long col = 0; col < size; col++) {
                long total = 0;
                for (long k = 0; k < size; k++)
                    total += left[(int)(row * size + k)] * right[(int)(k * size + col)];
                output[(int)(row * size + col)] = total;
            }
        }
        long checksum = 0;
        for (long value : output) checksum += value;
        return checksum;
    }
}
