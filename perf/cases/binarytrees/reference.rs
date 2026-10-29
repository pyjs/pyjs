struct Node { left: Option<Box<Node>>, right: Option<Box<Node>> }
impl Node {
    fn count(&self) -> i64 {
        match (&self.left, &self.right) {
            (Some(left), Some(right)) => 1 + left.count() + right.count(),
            _ => 1,
        }
    }
}
fn make_tree(depth: i64) -> Box<Node> {
    if depth == 0 { return Box::new(Node { left: None, right: None }); }
    Box::new(Node { left: Some(make_tree(depth - 1)), right: Some(make_tree(depth - 1)) })
}
fn kernel(size: i64) -> i64 {
    let retained = make_tree(size);
    let mut checksum = 0;
    for _ in 0..4 {
        let transient = make_tree(size);
        checksum += transient.count();
    }
    checksum + retained.count()
}
