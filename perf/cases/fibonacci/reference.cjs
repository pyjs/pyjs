function fib(n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}
function kernel(size) { return fib(size); }
