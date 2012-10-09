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

from pyjamas.Timer import Timer

from game_model import FPS, ROTATE_SPEED


class Controller:
    def __init__(self, model):
        self.model = model
        self.key_up = False
        self.key_down = False
        self.key_left = False
        self.key_right = False
        self.key_fire = False

    def start_game(self, view):
        self.view = view
        self.model.start_game(view)
        self.model.reset()

        #setup a timer
        self.timer = Timer(notify=self.update)
        self.timer.scheduleRepeating(1000/FPS)

    def update(self):
        self.keyboard_updates()
        self.model.update()

    def keyboard_updates(self):
        ship = self.model.ship

        drot = 0
        if self.key_left:
            drot -= ROTATE_SPEED
        if self.key_right:
            drot += ROTATE_SPEED
        if drot:
            ship.rotate_ship(drot)

        if self.key_up:
            ship.thrust()
        else:
            ship.friction()

        if self.key_fire:
            self.model.trigger_fire()
