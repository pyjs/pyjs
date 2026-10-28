public final class Kernel {
    static final class Body {
        double x, y, z, vx, vy, vz, mass;
        Body(long index) {
            x = index + 1; y = index % 3 - 1; z = index % 2 * 0.5;
            vx = 0.0; vy = (index + 1) * 0.01; vz = 0.0; mass = 1.0 + index * 0.1;
        }
    }
    public static long kernel(long size) {
        Body[] bodies = new Body[8];
        for (int i = 0; i < 8; i++) bodies[i] = new Body(i);
        for (long step = 0; step < size; step++) {
            for (int i = 0; i < 8; i++) {
                for (int j = i + 1; j < 8; j++) {
                    Body a = bodies[i], b = bodies[j];
                    double dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
                    double distance2 = dx * dx + dy * dy + dz * dz + 1.0;
                    double magnitude = 0.001 / (distance2 * Math.sqrt(distance2));
                    a.vx -= dx * b.mass * magnitude; a.vy -= dy * b.mass * magnitude; a.vz -= dz * b.mass * magnitude;
                    b.vx += dx * a.mass * magnitude; b.vy += dy * a.mass * magnitude; b.vz += dz * a.mass * magnitude;
                }
            }
            for (Body body : bodies) {
                body.x += 0.001 * body.vx; body.y += 0.001 * body.vy; body.z += 0.001 * body.vz;
            }
        }
        double checksum = 1000.0;
        for (int i = 0; i < 8; i++) {
            Body body = bodies[i];
            checksum += (i + 1) * (body.x + 2.0 * body.y + 3.0 * body.z);
        }
        return (long) (checksum * 1000000.0);
    }
}
