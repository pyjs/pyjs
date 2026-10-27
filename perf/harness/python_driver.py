"""Executed by the explicitly selected CPython, not the compiler interpreter."""
import sys
import time

from program import batch

size, loops, warmups, samples = map(int, sys.argv[1:])
for index in range(warmups + samples):
    start = time.perf_counter_ns()
    result = batch(size, loops)
    elapsed = time.perf_counter_ns() - start
    print("warmup" if index < warmups else "sample", result, elapsed, flush=True)
