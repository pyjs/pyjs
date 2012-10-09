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
import pyjd # this is dummy in pyjs.
from pyjamas import DOM

from pyjamas.ui import Event
from pyjamas.ui import KeyboardListener

from pyjamas.ui.Button import Button
from pyjamas.ui.ClickListener import ClickHandler
from pyjamas.ui.FocusPanel import FocusPanel
from pyjamas.ui.HTML import HTML
from pyjamas.ui.Image import Image
from pyjamas.ui.KeyboardListener import KeyboardHandler
from pyjamas.ui.RootPanel import RootPanel, RootPanelCls

from pyjamas.Canvas import Color
from pyjamas.Canvas.GWTCanvas import GWTCanvas
from pyjamas.Canvas.ImageLoader import loadImages


from game_model import Model, ASTEROID_SIZE
from game_controller import Controller


SHOT_COLOR = Color.Color('#fff')


class GameCanvas(GWTCanvas):
    def __init__(self, w, h):
        GWTCanvas.__init__(self, w, h)
        self.width = w
        self.height = h
        
        self.model = Model(w, h)
        self.controller = Controller(self.model)

        images = ['./images/ship1.png',
                  './images/ship2.png',
                  './images/asteroid.png']
        loadImages(images, self)

        self.sinkEvents(Event.KEYEVENTS)

    def onImagesLoaded(self, imagesHandles):
        self.ship = imagesHandles[0]
        self.ship_thrust = imagesHandles[1]
        self.asteroid = imagesHandles[2]

        self.resize(self.width, self.height)

        self.controller.start_game(self)

    def addTo(self, panel):
        panel.add(self)
        self.top = DOM.getAbsoluteTop(self.getElement())
        self.left = DOM.getAbsoluteLeft(self.getElement())


    def setKey(self, k, set):
        DOM.eventPreventDefault(DOM.eventGetCurrentEvent())
        if k == 38:
            self.controller.key_up = set
        elif k == 40:
            self.controller.key_down = set
        elif k == 37:
            self.controller.key_left = set
        elif k == 39:
            self.controller.key_right = set
        elif k == 32:
            self.controller.key_fire = set

    def onKeyDown(self, sender, keyCode, modifiers = None):
        self.setKey(keyCode, True)

    def onKeyUp(self, sender, keyCode, modifiers = None):
        self.setKey(keyCode, False)


    def draw_asteroid(self, asteroid):
        self.saveContext()
        self.translate(asteroid.x, asteroid.y)
        self.rotate(asteroid.rot)
        self.scale(asteroid.scale,asteroid.scale)
        self.drawImage(self.asteroid, -(ASTEROID_SIZE/2), -(ASTEROID_SIZE/2))
        self.restoreContext()

    def draw_shot(self, shot):
        self.setFillStyle(SHOT_COLOR)
        self.fillRect(int(shot.x - 1), int(shot.y - 1), 3, 3)
        
    def draw_ship(self, ship):
        self.saveContext()
        self.translate(ship.x, ship.y)
        self.rotate(ship.rot)
        if self.controller.key_up:
            img = self.ship_thrust
        else:
            img = self.ship
        self.drawImage(img, -15, -12)
        self.restoreContext()

        
    def draw(self):
        self.setFillStyle(Color.Color('#000'))
        self.fillRect(0,0,self.width,self.height)

        for a in self.model.asteroids:
            self.draw_asteroid(a)
        for s in self.model.shots:
            self.draw_shot(s)
            
        self.draw_ship(self.model.ship)


class RootPanelListener(RootPanelCls, KeyboardHandler, ClickHandler):
    def __init__(self, Parent, *args, **kwargs):
        self.Parent = Parent
        self.focussed = False
        RootPanelCls.__init__(self, *args, **kwargs)
        ClickHandler.__init__(self)
        KeyboardHandler.__init__(self)

        self.addClickListener(self)

    def onClick(self, Sender):
        self.focussed = not self.focussed
        self.Parent.setFocus(self.focussed)

if __name__ == '__main__':
    pyjd.setup("public/Space.html")
    c = GameCanvas(800, 600)
    panel = FocusPanel(Widget=c)
    RootPanel().add(panel)
    panel.addKeyboardListener(c)
    panel.setFocus(True)
    RootPanel().add(HTML("""
<hr/>
Left/Right arrows turn, Up key thrusts, Space bar fires<br/>
<a href="http://rumsey.org/blog/?p=215">About Space Game</a> by <a href="http://rumsey.org/blog/">Ogre</a><br/>
Written entirely in Python, using <a href="http://pyjs.org/">Pyjamas</a></br>
Copyright &copy; 2009 Joe Rumsey
"""))

    #c.getElement().focus()
    pyjd.run()
