class Ball {
    constructor(index) {
        this.x = index * 37 % 500; this.y = index * 53 % 500;
        this.vx = index % 17 + 1; this.vy = index % 23 + 1;
    }
    step() {
        this.x += this.vx; this.y += this.vy;
        if (this.x > 500) { this.x = 1000 - this.x; this.vx = -this.vx; }
        if (this.x < 0) { this.x = -this.x; this.vx = -this.vx; }
        if (this.y > 500) { this.y = 1000 - this.y; this.vy = -this.vy; }
        if (this.y < 0) { this.y = -this.y; this.vy = -this.vy; }
    }
}
function kernel(size) {
    const balls = [];
    for (let i = 0; i < 100; i++) balls.push(new Ball(i));
    for (let step = 0; step < size; step++) for (const ball of balls) ball.step();
    let checksum = 0;
    for (let i = 0; i < 100; i++) checksum += (i + 1) * (balls[i].x + 501 * balls[i].y);
    return checksum;
}
