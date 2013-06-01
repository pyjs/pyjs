# -*- coding: utf-8 -*-
"""
Created on Thu Dec  9 12:41:53 2010

@author: Alexander Tsepkov
"""

from pyjamas.Canvas.GWTCanvasImplIE6 import GWTCanvasImplIE6


"""
This is a dummy class for Internet Explorer browsers older than version 9. It
doesn't implement the additional HTML5 Canvas functionality, simply allows IE
to fail in a way that gives feedback back to the user/developer.
"""
class HTML5CanvasImplIE6(GWTCanvasImplIE6):

    def clearRect(self, x, y, w, h):
        raise NotImplementedError

    def clip(self):
        raise NotImplementedError

    def createImageData(self, sw, sh):
        raise NotImplementedError

    def getFont(self):
        raise NotImplementedError

    def getImageData(self, sx, sy, sw, sh):
        raise NotImplementedError

    def getShadowBlur(self):
        raise NotImplementedError

    def getShadowColor(self):
        raise NotImplementedError

    def getShadowOffsetX(self):
        raise NotImplementedError

    def getShadowOffsetY(self):
        raise NotImplementedError

    def getTextAlign(self):
        raise NotImplementedError

    def getTextBaseline(self):
        raise NotImplementedError

    def measureText(self, text):
        raise NotImplementedError

    def putImageData(self, imagedata, dx, dy, dirtyX, dirtyY, dirtyWidth, dirtyHeight):
        raise NotImplementedError

    def setFont(self, value):
        raise NotImplementedError

    def setShadowBlur(self, blur):
        raise NotImplementedError

    def setShadowColor(self, color):
        raise NotImplementedError

    def setShadowOffset(self, x, y):
        raise NotImplementedError

    def setTextAlign(self, loc):
        raise NotImplementedError

    def setTextBaseline(self, loc):
        raise NotImplementedError

    def toDataURL(self, type):
        raise NotImplementedError
