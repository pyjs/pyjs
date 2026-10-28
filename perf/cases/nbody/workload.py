import math


class Body:
    def __init__(self, index: int):
        self.x = float(index + 1)
        self.y = float(index % 3 - 1)
        self.z = float(index % 2) * 0.5
        self.vx = 0.0
        self.vy = float(index + 1) * 0.01
        self.vz = 0.0
        self.mass = 1.0 + float(index) * 0.1


def kernel(size: int) -> int:
    bodies: list[Body] = []
    for i in range(8):
        bodies.append(Body(i))
    for _ in range(size):
        for i in range(8):
            for j in range(i + 1, 8):
                a = bodies[i]
                b = bodies[j]
                dx = a.x - b.x
                dy = a.y - b.y
                dz = a.z - b.z
                distance2 = dx * dx + dy * dy + dz * dz + 1.0
                magnitude = 0.001 / (distance2 * math.sqrt(distance2))
                a.vx -= dx * b.mass * magnitude
                a.vy -= dy * b.mass * magnitude
                a.vz -= dz * b.mass * magnitude
                b.vx += dx * a.mass * magnitude
                b.vy += dy * a.mass * magnitude
                b.vz += dz * a.mass * magnitude
        for body in bodies:
            body.x += 0.001 * body.vx
            body.y += 0.001 * body.vy
            body.z += 0.001 * body.vz
    checksum = 1000.0
    for i in range(8):
        body = bodies[i]
        checksum += (i + 1) * (body.x + 2.0 * body.y + 3.0 * body.z)
    return int(checksum * 1000000.0)
