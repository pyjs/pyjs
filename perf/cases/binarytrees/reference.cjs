class Node {
    constructor(left, right) { this.left = left; this.right = right; }
    count() {
        const left = this.left, right = this.right;
        if (left === null || right === null) return 1;
        return 1 + left.count() + right.count();
    }
}
function makeTree(depth) {
    if (depth === 0) return new Node(null, null);
    return new Node(makeTree(depth - 1), makeTree(depth - 1));
}
function kernel(size) {
    const retained = makeTree(size);
    let checksum = 0;
    for (let i = 0; i < 4; i++) {
        const transient = makeTree(size);
        checksum += transient.count();
    }
    return checksum + retained.count();
}
