struct Ball { x: i64, y: i64, vx: i64, vy: i64 }
impl Ball {
    fn new(index: i64) -> Self {
        Self { x: index * 37 % 500, y: index * 53 % 500, vx: index % 17 + 1, vy: index % 23 + 1 }
    }
    fn step(&mut self) {
        self.x += self.vx; self.y += self.vy;
        if self.x > 500 { self.x = 1000 - self.x; self.vx = -self.vx; }
        if self.x < 0 { self.x = -self.x; self.vx = -self.vx; }
        if self.y > 500 { self.y = 1000 - self.y; self.vy = -self.vy; }
        if self.y < 0 { self.y = -self.y; self.vy = -self.vy; }
    }
}
fn kernel(size: i64) -> i64 {
    let mut balls = Vec::new();
    for i in 0..100 { balls.push(Ball::new(i)); }
    for _ in 0..size { for ball in &mut balls { ball.step(); } }
    let mut checksum = 0;
    for i in 0..100 { checksum += (i as i64 + 1) * (balls[i].x + 501 * balls[i].y); }
    checksum
}
