# -*- coding: utf-8 -*-
"""
Created on Sun Nov 28 19:22:15 2010

@author: Alexander Tsepkov
"""

from pyjamas.Canvas.GWTCanvas import GWTCanvas
from pyjamas.Canvas.HTML5CanvasImplDefault import HTML5CanvasImplDefault
from pyjamas.Canvas.Color import Color
from pyjamas.Canvas.ImageData import ImageData



"""
This module further expands GWTCanvas to cover newer HTML5 canvas functionality.
Note that this API is incompatible with Internet Explorer older than version 9.
"""
class HTML5Canvas(GWTCanvas):


    def getCanvasImpl(self):
        return HTML5CanvasImplDefault()

    def clearRect(self, x, y, w, h):
        self.impl.clearRect(x, y, w, h)

    """
    clips the current path
    """
    def clip(self):
        self.impl.clip()

    """
    Returns an ImageData object with the given dimensions in CSS pixels (which
    might map to a different number of actual device pixels exposed by the
    object itself). All the pixels in the returned object are transparent black.
    """
    def createImageData(self, sw, sh):
        return ImageData(self.impl.createImageData(sw, sh))

    """
    Returns an ImageData object containing the image data for the given
    rectangle of the canvas.
    """
    def getImageData(self, sx, sy, sw, sh):
        return ImageData(self.impl.getImageData(sx, sy, sw, sh))

    """
    Paints the data from the given ImageData object onto the canvas. If a dirty
    rectangle is provided, only the pixels from that rectangle are painted.
    """
    def putImageData(self, imagedata, dx, dy, dirtyX=0, dirtyY=0, dirtyWidth=None, dirtyHeight=None):
        if dirtyWidth == None:
            dirtyWidth = self.coordWidth
        if dirtyHeight == None:
            dirtyHeight = self.coordHeight
        self.impl.putImageData(imagedata, dx, dy, dirtyX, dirtyY, dirtyWidth, dirtyHeight)

    """
    returns the canvas data as a base64 encoded PNG file, also supports
    image/jpg in Firefox
    """
    def toDataURL(self, type="image/png"):
        return self.impl.toDataURL(type)

    """
    Returns a string corresponding to current font size and type, for example:
    "10px monospace"
    """
    def getFont(self):
        return self.impl.getFont()

    """
    returns the width in pixels the passed in string would take up when drawn
    with currently set font size and type
    """
    def measureText(self, text):
        return self.impl.measureText(text)

    """
    Sets current font to passed in size and type, if the string is in invalid
    format, the font will not be updated
    """
    def setFont(self, value):
        self.impl.setFont(value)

    """
    returns the current level of blur applied to shadows
    """
    def getShadowBlur(self):
        return self.impl.getShadowBlur()

    """
    returns the current shadow color
    """
    def getShadowColor(self):
        return Color(self.impl.getShadowColor())

    """
    returns the current horizontal shadow offset
    """
    def getShadowOffsetX(self):
        self.impl.getShadowOffsetX()

    """
    Returns the current text alignment settings
    """
    def getTextAlign(self):
        return self.impl.getTextAlign()

    """
    Returns the current text baseline settings
    """
    def getTextBaseline(self):
        return self.impl.getTextBaseline()

    """
    returns the current vertical shadow offset
    """
    def getShadowOffsetY(self):
        self.impl.getShadowOffsetY()

    """
    sets blur level of shadows, values that are not finite numbers greater
    than or equal to zero are ignored
    """
    def setShadowBlur(self, blur):
        self.impl.setShadowBlur(blur)

    """
    sets the current shadow color
    """
    def setShadowColor(self, color):
        self.impl.setShadowColor(str(color))

    """
    sets the current shadow offset
    """
    def setShadowOffset(self, x, y):
        self.impl.setShadowOffset(x, y)

    """
    Sets the current text alignment settings. The possible values are start,
    end, left, right, and center
    """
    def setTextAlign(self, loc):
        self.impl.setTextAlign(loc)
    
    """
    Sets the current text baseline settings. The possible values are alphabetic,
    bottom, hanging, ideographic, middle, and top
    """
    def setTextBaseline(self, loc):
        self.impl.setTextBaseline(loc)
