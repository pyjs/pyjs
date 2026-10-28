struct Body { x: f64, y: f64, z: f64, vx: f64, vy: f64, vz: f64, mass: f64 }
impl Body {
    fn new(index: i64) -> Self {
        Self { x: (index + 1) as f64, y: (index % 3 - 1) as f64, z: (index % 2) as f64 * 0.5,
            vx: 0.0, vy: (index + 1) as f64 * 0.01, vz: 0.0, mass: 1.0 + index as f64 * 0.1 }
    }
}
fn kernel(size: i64) -> i64 {
    let mut bodies = Vec::new();
    for i in 0..8 { bodies.push(Body::new(i)); }
    for _ in 0..size {
        for i in 0..8 {
            for j in i + 1..8 {
                // Disjoint mutable borrows, with the same pair order and updates.
                let (left, right) = bodies.split_at_mut(j);
                let a = &mut left[i]; let b = &mut right[0];
                let dx = a.x - b.x; let dy = a.y - b.y; let dz = a.z - b.z;
                let distance2 = dx * dx + dy * dy + dz * dz + 1.0;
                let magnitude = 0.001 / (distance2 * distance2.sqrt());
                a.vx -= dx * b.mass * magnitude; a.vy -= dy * b.mass * magnitude; a.vz -= dz * b.mass * magnitude;
                b.vx += dx * a.mass * magnitude; b.vy += dy * a.mass * magnitude; b.vz += dz * a.mass * magnitude;
            }
        }
        for body in &mut bodies {
            body.x += 0.001 * body.vx; body.y += 0.001 * body.vy; body.z += 0.001 * body.vz;
        }
    }
    let mut checksum = 1000.0;
    for i in 0..8 {
        let body = &bodies[i];
        checksum += (i + 1) as f64 * (body.x + 2.0 * body.y + 3.0 * body.z);
    }
    (checksum * 1000000.0) as i64
}
