# Canvas wrapper component for Pyjamas
# Ported by Willie Gollino from Canvas component for GWT - Originally by Alexei Sokolov http://gwt.components.googlepages.com/
#
# Canvas API reference:
# http://developer.apple.com/documentation/AppleApplications/Reference/SafariJSRef/Classes/Canvas.html#//apple_ref/js/Canvas.clearRect
#
# Usage Notes:
#   - IE support requires ExplorerCanvas from excanvas.sourceforge.net
#   - place excanvas.js in your apps public folder
#   - add this to your MainModule.html: <!--[if IE]><script src="excanvas.js" type="text/javascript"></script><![endif]-->

from pyjamas import DOM
from pyjamas.ui.Image import Image
from pyjamas.ui.FocusWidget import FocusWidget
from pyjamas.ui import Event
from pyjamas.ui import MouseListener
from pyjamas.ui import KeyboardListener
from pyjamas.ui import Focus
from pyjamas.ui import FocusListener

from __pyjamas__ import JS

class Canvas(FocusWidget):
    def __init__(self, Width=0, Height=0, **kwargs):
        if not kwargs.has_key('StyleName'):
            kwargs['StyleName'] = 'gwt-Canvas'
        kwargs['Width'] = Width
        kwargs['Height'] = Height

        self.context = None

        focusable = Focus.createFocusable()
        self.canvas = DOM.createElement("canvas")
        DOM.appendChild(focusable, self.canvas)
        FocusWidget.__init__(self, focusable, **kwargs)

        self.init()

        self.context.fillStyle = "black"
        self.context.strokeStyle = "black"

        #add onImageLoad, since some listeners use it
        self.onImageLoad = self.onLoad

    def setWidth(self, width):
        FocusWidget.setWidth(self, width)
        self.canvas.width = width

    def setHeight(self, height):
        FocusWidget.setHeight(self, height)
        self.canvas.height = height

    def getContext(self):
        return self.context

    def isEmulation(self):
        return False

    def init(self):
        el = self.getElement().firstChild
        ctx = el.getContext("2d")

        """
        ctx._createPattern = ctx.createPattern
        ctx.createPattern = function(img, rep) {
            if (!(img instanceof Image)) img = img.getElement();
            return self._createPattern(img, rep)
            }

        ctx._drawImage = ctx.drawImage
        ctx.drawImage = function() {
            var a=arguments
            if (!(a[0] instanceof Image)) a[0] = a[0].getElement()
            if (a.length==9) return self._drawImage(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8])
            else if (a.length==5) return self._drawImage(a[0], a[1], a[2], a[3], a[4])
            return self._drawImage(a[0], a[1], a[2])
            }
        """
        self.context = ctx

class CanvasImage(Image):
    def __init__(self, url="", load_listener = None):
        Image.__init__(self, url)
        if load_listener:
            self.addLoadListener(load_listener)
        self.onAttach()

    def isLoaded(self):
        return self.getElement().complete


class ImageLoadListener:
    def __init__(self, listener = None):
        self.wait_list = []
        self.loadListeners = []

        if listener:
            self.addLoadListener(listener)

        self.onImageLoad = self.onLoad

    def add(self, sender):
        self.wait_list.append(sender)
        sender.addLoadListener(self)

    def addLoadListener(self, listener):
        self.loadListeners.append(listener)

    def isLoaded(self):
        if len(self.wait_list):
            return False
        return True

    def onError(self, sender):
        for listener in self.loadListeners:
            listener.onError(sender)

    def onLoad(self, sender):
        self.wait_list.remove(sender)

        if self.isLoaded():
            for listener in self.loadListeners:
                listener.onLoad(self)
