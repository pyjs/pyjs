public final class Kernel {
    static long fib(long n) {
        if (n < 2) return n;
        return fib(n - 1) + fib(n - 2);
    }
    public static long kernel(long size) { return fib(size); }
}
