# -*- coding: utf-8 -*-
"""
Created on Mon Nov 29 12:23:20 2010

@author: Alexander Tsepkov
"""

from pyjamas.Canvas.GWTCanvasImplDefault import GWTCanvasImplDefault


class HTML5CanvasImplDefault(GWTCanvasImplDefault):

    def clearRect(self, x, y, w, h):
        self.canvasContext.clearRect(x, y, w, h)

    def clip(self):
        self.canvasContext.clip()

    def createImageData(self, sw, sh):
        return self.canvasContext.createImageData(sw, sh)

    def getFont(self):
        return self.canvasContext.font

    def getImageData(self, sx, sy, sw, sh):
        return self.canvasContext.getImageData(sx, sy, sw, sh)

    def getShadowBlur(self):
        return self.canvasContext.shadowBlur

    def getShadowColor(self):
        return self.canvasContext.shadowColor

    def getShadowOffsetX(self):
        return self.canvasContext.shadowOffsetX

    def getShadowOffsetY(self):
        return self.canvasContext.shadowOffsetY

    def getTextAlign(self):
        return self.canvasContext.textAlign
    
    def getTextBaseline(self):
        return self.canvasContext.textBaseline
    
    def measureText(self, text):
        return self.canvasContext.measureText(text).width

    def putImageData(self, imagedata, dx, dy, dirtyX, dirtyY, dirtyWidth, dirtyHeight):
        self.canvasContext.putImageData(imagedata, dx, dy, dirtyX, dirtyY, dirtyWidth, dirtyHeight)

    def setFont(self, value):
        self.canvasContext.font = value

    def setShadowBlur(self, blur):
        self.canvasContext.shadowBlur = blur

    def setShadowColor(self, color):
        self.canvasContext.shadowColor = color

    def setShadowOffset(self, x, y):
        self.canvasContext.shadowOffsetX = x
        self.canvasContext.shadowOffsetY = y

    def setTextAlign(self, loc):
        self.canvasContext.textAlign = loc
    
    def setTextBaseline(self, loc):
        self.canvasContext.textBaseline = loc

    def toDataURL(self, type):
        return self.canvasContext.toDataURL(type)
