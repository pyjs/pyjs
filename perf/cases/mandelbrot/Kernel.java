public final class Kernel {
    public static long kernel(long size) {
        long checksum = 0;
        for (long y = 0; y < size; y++) {
            double ci = y * 2.0 / size - 1.0;
            for (long x = 0; x < size; x++) {
                double cr = x * 2.0 / size - 1.5;
                double zr = 0.0, zi = 0.0;
                long count = 0;
                while (count < 50 && zr * zr + zi * zi <= 4.0) {
                    double nextReal = zr * zr - zi * zi + cr;
                    zi = 2.0 * zr * zi + ci;
                    zr = nextReal;
                    count++;
                }
                checksum += (y * size + x + 1) * count;
            }
        }
        return checksum;
    }
}
