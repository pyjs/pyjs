class Body {
    constructor(index) {
        this.x = index + 1; this.y = index % 3 - 1; this.z = index % 2 * 0.5;
        this.vx = 0.0; this.vy = (index + 1) * 0.01; this.vz = 0.0;
        this.mass = 1.0 + index * 0.1;
    }
}
function kernel(size) {
    const bodies = [];
    for (let i = 0; i < 8; i++) bodies.push(new Body(i));
    for (let step = 0; step < size; step++) {
        for (let i = 0; i < 8; i++) {
            for (let j = i + 1; j < 8; j++) {
                const a = bodies[i], b = bodies[j];
                const dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
                const distance2 = dx * dx + dy * dy + dz * dz + 1.0;
                const magnitude = 0.001 / (distance2 * Math.sqrt(distance2));
                a.vx -= dx * b.mass * magnitude; a.vy -= dy * b.mass * magnitude; a.vz -= dz * b.mass * magnitude;
                b.vx += dx * a.mass * magnitude; b.vy += dy * a.mass * magnitude; b.vz += dz * a.mass * magnitude;
            }
        }
        for (const body of bodies) {
            body.x += 0.001 * body.vx; body.y += 0.001 * body.vy; body.z += 0.001 * body.vz;
        }
    }
    let checksum = 1000.0;
    for (let i = 0; i < 8; i++) {
        const body = bodies[i];
        checksum += (i + 1) * (body.x + 2.0 * body.y + 3.0 * body.z);
    }
    return Math.trunc(checksum * 1000000.0);
}
