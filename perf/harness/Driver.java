public final class Driver {
    public static void main(String[] args) {
        long size = Long.parseLong(args[0]);
        long loops = Long.parseLong(args[1]);
        int warmups = Integer.parseInt(args[2]);
        int samples = Integer.parseInt(args[3]);
        for (int i = 0; i < warmups + samples; i++) {
            long start = System.nanoTime();
            String result = BATCH(size, loops);
            long elapsed = System.nanoTime() - start;
            System.out.println((i < warmups ? "warmup" : "sample") + " " + result + " " + elapsed);
        }
    }
}
