""" testing our demo slider
"""
import pyjd # dummy in pyjs

from pyjamas.ui.Label      import Label
from pyjamas.ui.Button     import Button
from pyjamas.ui.ButtonBase import ButtonBase
from pyjamas.ui.RootPanel  import RootPanel
from pyjamas.ui.ToggleButton import ToggleButton
from pyjamas.ui.PushButton import PushButton
from pyjamas               import DOM
from pyjamas.ui.Image      import Image
from pyjamas.ui.VerticalPanel import VerticalPanel
from pyjamas.ui.HorizontalPanel import HorizontalPanel

class Toggle:
    def onModuleLoad(self):

        self.label = Label("Not set yet")

        self.button = Button("Probe button", self)
        self.image_up = Image("./images/logo.png")
        self.image_up3 = Image("./images/logo.png")
        self.image_down = Image("./images/logo.png")
        self.image_down3 = Image("./images/logo.png")
        self.toggle = ToggleButton(self.image_up, self.image_down, self)
        self.toggle2 = ToggleButton("up", "down", getattr(self, "onToggleUD"))
        self.push = PushButton(self.image_up3, self.image_down3)

        self.vpanel = VerticalPanel()
        self.togglePanel = HorizontalPanel()
        self.togglePanel.setSpacing(10)

        self.togglePanel.add(self.toggle)
        self.togglePanel.add(self.toggle2)
        self.togglePanel.add(self.push)

        self.vpanel.add(self.label)
        self.vpanel.add(self.button)
        self.vpanel.add(self.togglePanel)

        RootPanel().add(self.vpanel)
        self.i = False

    def onToggleUD(self, sender):
            self.label.setText(" Toggle2 isdown: "+str(self.toggle2.isDown()))

    def onClick(self, sender):
        if sender == self.button:
            if self.i:
                self.i = False
                text = ">>>>UP<<<<"
                self.toggle.setCurrentFace(self.toggle.getUpFace())
            else:
                self.i = True
                text = ">>>DOWN<<<"
                self.toggle.setCurrentFace(self.toggle.getDownFace())
            #self.label.setText("self.toggle.style_name: "+
            #                    self.toggle.style_name+", self.toggle.getStyleName():"+
            #                    self.toggle.getStyleName()+" ")
            self.label.setText(text)
        elif sender == self.toggle:
            text = ">>>DOWN<<<"
            if self.i: text = ">>>>UP<<<<"
            self.i = not self.i
            self.label.setText(text+" isdown: "+str(self.toggle.isDown()))


if __name__ == "__main__":
    pyjd.setup("./public/Toggle.html")
    app = Toggle()
    app.onModuleLoad()
    pyjd.run()


