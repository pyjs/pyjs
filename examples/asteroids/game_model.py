#   Copyright 2009 Joe Rumsey (joe@rumsey.org)
#   Copyright 2012 Charles Law (charles.law@gmail.com)
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#

import math
import random

NUM_ASTEROIDS = 2
FPS = 30
FRICTION = 0.05
THRUST = 0.2
ROTATE_SPEED_PER_SEC = Math.PI
ROTATE_SPEED = ROTATE_SPEED_PER_SEC / FPS
MAX_ASTEROID_SPEED = 2.0
SHOT_LIFESPAN = 60
SHOT_SPEED = 8.0
SHOT_DELAY = 10
ASTEROID_SIZE = 180.0
ASTEROID_SIZES = [90.0, 45.0, 22.0, 11.0]


def randfloat(absval):
    return (random.random() * (2 * absval) - absval)


def distsq(x1,y1, x2,y2):
    return ((x1 - x2) * (x1 - x2)) + ((y1 - y2) * (y1 - y2))


class Asteroid:
    def __init__(self, model, x=None, y=None, size=0):
        self.model = model
        if x is None or y is None:
            self.x = model.x/2
            self.y = model.y/2
            while distsq(self.x, self.y, model.x / 2, model.y / 2) < (180*180):
                self.x = random.randint(0, model.x)
                self.y = random.randint(0, model.y)
        else:
            self.x = x
            self.y = y

        self.dx = randfloat(MAX_ASTEROID_SPEED)
        self.dy = randfloat(MAX_ASTEROID_SPEED)
        self.rot = (random.random() * (2 * math.pi)) - math.pi
        self.rotspeed = (random.random() * 0.1) - 0.05
        self.size = size
        self.radius = ASTEROID_SIZES[self.size]
        self.radius2 = self.radius*self.radius
        self.scale = (self.radius / ASTEROID_SIZE) * 2

    def update_dim(self, pos, d_dim, max_dim):
        pos += d_dim

        if d_dim < 0:
            if pos <= 0:
                pos = -pos
                d_dim = -d_dim
        else:
            if pos >= max_dim:
                d_dim = -d_dim
                pos = 2*max_dim - pos
        return pos, d_dim

    def move(self):
        self.x, self.dx = self.update_dim(self.x, self.dx, self.model.x)
        self.y, self.dy = self.update_dim(self.y, self.dy, self.model.y)

        self.rot += self.rotspeed


class Shot:
    def __init__(self, model, ship):
        self.model = model
        self.x = ship.x
        self.y = ship.y
        self.dx = ship.dx
        self.dy = ship.dy
        self.dir = ship.rot
        self.lifespan = SHOT_LIFESPAN

    def move(self):
        self.lifespan -= 1
        if self.lifespan <= 0:
            return False
        self.x = self.x + self.dx + SHOT_SPEED * math.sin(self.dir)
        self.y = self.y + self.dy - SHOT_SPEED * math.cos(self.dir)
        for i in range(len(self.model.asteroids)):
            a = self.model.asteroids[i]
            if distsq(self.x, self.y, a.x, a.y) < (a.radius2):
                self.model.split_asteroid(i)
                return False

        return True


class Ship:
    def __init__(self, cx, cy):
        self.cx = cx
        self.cy = cy
        self.reset()

    def rotate_ship(self, drot):
        self.rot += drot
        
        if drot < 0-math.pi:
            drot += 2*math.pi
        elif drot > math.pi:
            drot -= 2*math.pi
    
    def thrust(self):
        self.dx += THRUST * math.sin(self.rot)
        self.dy -= THRUST * math.cos(self.rot)
    
    def friction(self):
        if math.fabs(self.dx) < 0.001 and math.fabs(self.dy) < 0.001:
            self.dx = 0
            self.dy = 0
        else:
            dir = math.atan2(self.dx, self.dy)
            self.dx -= FRICTION * math.sin(dir)
            self.dy -= FRICTION * math.cos(dir)

    def move(self):
        self.shot_delay -= 1

        self.x += self.dx
        self.y += self.dy
        if self.dx > 0 and self.x >= self.cx:
            self.x -= self.cx
        elif self.dx < 0 and self.x < 0:
            self.x += self.cx
        if self.y > 0 and self.y >= self.cy:
            self.y -= self.cy
        elif self.dy < 0 and self.y < 0:
            self.y += self.cy

    def reset(self):
        self.x = self.cx/2
        self.y = self.cy/2
        self.dx = 0
        self.dy = 0
        self.rot = 0
        self.shot_delay = 0


class Model:
    def __init__(self, x, y):
        self.x = x
        self.y = y

        self.num_asteroids = NUM_ASTEROIDS

        self.ship = Ship(x, y)

    def start_game(self, view):
        self.view = view

    def update(self):
        # Make model updates
        for a in self.asteroids:
            a.move()
            if (distsq(self.ship.x, self.ship.y, a.x, a.y) < (a.radius2)):
                self.destroyShip()
                return

        for i in reversed(range(len(self.shots))):
            if not self.shots[i].move():
                self.shots.pop(i)
                
                if len(self.asteroids) == 0:
                    self.start_next_level()
                    return

        self.ship.move()

        self.view.draw()

    def start_next_level(self):
        self.num_asteroids += 1
        self.reset()

    def destroyShip(self):
        self.num_asteroids = NUM_ASTEROIDS
        self.reset()

    def reset(self):
        self.shots = []
        self.asteroids = [Asteroid(self) for i in range(self.num_asteroids)]
        self.ship.reset()

    def trigger_fire(self):
        if self.ship.shot_delay > 0:
            return
        else:
            self.shots.append(Shot(self, self.ship))
            self.ship.shot_delay = SHOT_DELAY

    def split_asteroid(self, i):
        a = self.asteroids[i]
        if a.size < len(ASTEROID_SIZES) - 1:
            for j in range(2):
                self.asteroids.append(Asteroid(self, a.x, a.y, a.size + 1))
        self.asteroids.pop(i)
