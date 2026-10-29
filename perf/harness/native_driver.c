/* POSIX adapter for the existing PyJS renderer ABI; no Python at runtime.
 * Only one checksum is written per batch. Its serialization, write, arena
 * lifecycle, and exception checks are included, not subtracted from timings.
 */
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

/* DECLARATIONS */
static void report_error(void *trace, void *message, void *type) {
    (void)trace; (void)message; (void)type;
    fprintf(stderr, "PyJS native workload raised an exception\n");
}
static int64_t now_ns(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value)) exit(2);
    return (int64_t)value.tv_sec * 1000000000 + value.tv_nsec;
}
int main(int argc, char **argv) {
    if (argc != 5) return 2;
    int64_t size = strtoll(argv[1], NULL, 10), loops = strtoll(argv[2], NULL, 10);
    int warmups = atoi(argv[3]), samples = atoi(argv[4]);
    FILE *sink = tmpfile();
    if (!sink) return 2;
    /* INIT */
    for (int i = 0; i < warmups + samples; i++) {
        rewind(sink);
        if (ftruncate(fileno(sink), 0)) return 2;
        int64_t start = now_ns();
        int status = CALL;
        int64_t elapsed = now_ns() - start;
        if (status != 0) return 3;
        rewind(sink);
        char value[128] = {0};
        size_t count = fread(value, 1, sizeof(value) - 1, sink);
        if (ferror(sink) || count == sizeof(value) - 1) return 4;
        printf("%s %s %lld\n", i < warmups ? "warmup" : "sample", value, (long long)elapsed);
        fflush(stdout);
    }
    /* CLOSE */
    fclose(sink);
    return 0;
}
