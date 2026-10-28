class Ball:
    def __init__(self, index: int):
        self.x = index * 37 % 500
        self.y = index * 53 % 500
        self.vx = index % 17 + 1
        self.vy = index % 23 + 1

    def step(self) -> None:
        self.x += self.vx
        self.y += self.vy
        if self.x > 500:
            self.x = 1000 - self.x
            self.vx = -self.vx
        if self.x < 0:
            self.x = -self.x
            self.vx = -self.vx
        if self.y > 500:
            self.y = 1000 - self.y
            self.vy = -self.vy
        if self.y < 0:
            self.y = -self.y
            self.vy = -self.vy


def kernel(size: int) -> int:
    balls: list[Ball] = []
    for i in range(100):
        balls.append(Ball(i))
    for _ in range(size):
        for ball in balls:
            ball.step()
    checksum = 0
    for i in range(100):
        checksum += (i + 1) * (balls[i].x + 501 * balls[i].y)
    return checksum
