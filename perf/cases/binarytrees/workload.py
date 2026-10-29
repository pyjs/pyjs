class Node:
    def __init__(self, left: Node | None, right: Node | None):
        self.left = left
        self.right = right

    def count(self) -> int:
        left = self.left
        right = self.right
        if left is None or right is None:
            return 1
        return 1 + left.count() + right.count()


def make_tree(depth: int) -> Node:
    if depth == 0:
        return Node(None, None)
    return Node(make_tree(depth - 1), make_tree(depth - 1))


def kernel(size: int) -> int:
    retained = make_tree(size)
    checksum = 0
    for _i in range(4):
        transient = make_tree(size)
        checksum += transient.count()
    return checksum + retained.count()
