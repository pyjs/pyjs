public final class Kernel {
    static final class Record {
        final long value;
        final long weight;
        Record(long value) { this.value = value; this.weight = value % 7; }
        long score() { return value * weight; }
    }
    public static long kernel(long size) {
        java.util.ArrayList<Record> records = new java.util.ArrayList<>();
        for (long i = 0; i < size; i++) records.add(new Record(i));
        long checksum = 0;
        for (Record record : records) checksum += record.score();
        return checksum;
    }
}
