import java.util.HashMap;
public final class Kernel {
    public static long kernel(long size) {
        HashMap<Long, Long> counts = new HashMap<>();
        for (long i = 0; i < size; i++) {
            long key = i * 17 % 257;
            counts.put(key, counts.getOrDefault(key, 0L) + 1);
        }
        long checksum = 0;
        for (long key : counts.keySet()) checksum += (key + 1) * counts.get(key);
        return checksum;
    }
}
