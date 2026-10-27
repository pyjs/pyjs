public final class Kernel {
    static final class Node {
        final Node left, right;
        Node(Node left, Node right) { this.left = left; this.right = right; }
        long count() {
            if (left == null || right == null) return 1;
            return 1 + left.count() + right.count();
        }
    }
    static Node makeTree(long depth) {
        if (depth == 0) return new Node(null, null);
        return new Node(makeTree(depth - 1), makeTree(depth - 1));
    }
    public static long kernel(long size) {
        Node retained = makeTree(size);
        long checksum = 0;
        for (int i = 0; i < 4; i++) {
            Node transientTree = makeTree(size);
            checksum += transientTree.count();
        }
        return checksum + retained.count();
    }
}
