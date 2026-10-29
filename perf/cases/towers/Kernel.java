import java.util.ArrayList;
public final class Kernel {
    static long move(ArrayList<ArrayList<Long>> piles, long count, int source, int destination) {
        if (count == 0) return 0;
        int other = 3 - source - destination;
        long moves = move(piles, count - 1, source, other);
        ArrayList<Long> from = piles.get(source);
        long disk = from.remove(from.size() - 1);
        piles.get(destination).add(disk);
        moves++;
        return moves + move(piles, count - 1, other, destination);
    }
    public static long kernel(long size) {
        ArrayList<Long> first = new ArrayList<>(), second = new ArrayList<>(), third = new ArrayList<>();
        for (long i = 0; i < size; i++) first.add(size - i);
        ArrayList<ArrayList<Long>> piles = new ArrayList<>();
        piles.add(first); piles.add(second); piles.add(third);
        long checksum = move(piles, size, 0, 2);
        if (!first.isEmpty() || !second.isEmpty() || third.size() != size) return -1;
        for (int i = 0; i < size; i++) {
            if (third.get(i) != size - i) return -1;
            checksum += (i + 1) * third.get(i);
        }
        return checksum;
    }
}
