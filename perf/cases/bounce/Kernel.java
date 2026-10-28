public final class Kernel {
    static final class Ball {
        long x, y, vx, vy;
        Ball(long index) {
            x = index * 37 % 500; y = index * 53 % 500;
            vx = index % 17 + 1; vy = index % 23 + 1;
        }
        void step() {
            x += vx; y += vy;
            if (x > 500) { x = 1000 - x; vx = -vx; }
            if (x < 0) { x = -x; vx = -vx; }
            if (y > 500) { y = 1000 - y; vy = -vy; }
            if (y < 0) { y = -y; vy = -vy; }
        }
    }
    public static long kernel(long size) {
        Ball[] balls = new Ball[100];
        for (int i = 0; i < 100; i++) balls[i] = new Ball(i);
        for (long step = 0; step < size; step++) for (Ball ball : balls) ball.step();
        long checksum = 0;
        for (int i = 0; i < 100; i++) checksum += (i + 1) * (balls[i].x + 501 * balls[i].y);
        return checksum;
    }
}
