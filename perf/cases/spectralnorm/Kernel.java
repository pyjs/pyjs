public final class Kernel {
    static double element(long i, long j) { return 1.0 / ((i + j) * (i + j + 1) / 2 + i + 1); }
    static void multiply(double[] source, double[] result, int size, boolean transpose) {
        for (int i = 0; i < size; i++) {
            double total = 0.0;
            for (int j = 0; j < size; j++) {
                if (transpose) total += element(j, i) * source[j];
                else total += element(i, j) * source[j];
            }
            result[i] = total;
        }
    }
    public static long kernel(long input) {
        int size = (int) input;
        if (size == 0) return 0;
        double[] u = new double[size], v = new double[size], temporary = new double[size];
        for (int i = 0; i < size; i++) u[i] = 1.0;
        for (int step = 0; step < 10; step++) {
            multiply(u, temporary, size, false); multiply(temporary, v, size, true);
            multiply(v, temporary, size, false); multiply(temporary, u, size, true);
        }
        double numerator = 0.0, denominator = 0.0;
        for (int i = 0; i < size; i++) { numerator += u[i] * v[i]; denominator += v[i] * v[i]; }
        return (long) (Math.sqrt(numerator / denominator) * 1000000000.0);
    }
}
