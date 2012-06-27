"""
* Copyright 2008 Google Inc.
* Copyright 2011 Bob Hampton
*
* Licensed under the Apache License, Version 2.0 (the "License"); you may not
* use this file except in compliance with the License. You may obtain a copy of
* the License at
*
* http:#www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
* WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
* License for the specific language governing permissions and limitations under
* the License.
"""

import math

from pyjamas import DOM
from __pyjamas__ import JS, doc
from pyjamas.ui.Widget import Widget

from pyjamas import Window


from pyjamas.Canvas.GWTCanvasImplIEConsts import BUTT, DESTINATION_OVER, SOURCE_OVER
from pyjamas.Canvas import GWTCanvasConsts
from pyjamas.Canvas.JSOStack import JSOStack
from pyjamas.Canvas import PathElement
from pyjamas.Canvas.VMLContext import VMLContext
from pyjamas.Canvas.VMLContext import VMLStyle
from pyjamas.Canvas.Color import Color
from pyjamas.Canvas.CanvasGradientImplIE6 import CanvasGradientImplIE6

def addNamespace():
    JS("""
    if (!$doc['namespaces']["v"]) {
        $doc['namespaces']['add']("v", "urn:schemas-microsoft-com:vml");
        $doc['createStyleSheet']()['cssText'] = "v\\:*{behavior:url(#default#VML);}";
    }
    """)


"""*
* Deferred binding implementation of GWTCanvas for IE6. It is an implementation
* of canvas on top of VML.
"""
class GWTCanvasImplIE6:

    def __init__(self):
        try:
            ns = doc().namespaces.item("v")
        except:
            doc().namespaces.add("v", "urn:schemas-microsoft-com:vml")
            doc().createStyleSheet().cssText = "v\\:*{behavior:url(#default#VML);}"



        """*
        * This will be used for an array join. Currently a bit faster than
        * StringBuilder.append() & toString() because of the extra collections
        * overhead.
        """
        self.pathStr = JSOStack()

        """*
        * Stack uses preallocated arrays which makes push() slightly faster than
        * [].push() since each push is simply an indexed setter.
        """
        self.contextStack = []

        self.currentX = 0

        self.currentY = 0

        self.parentElement = None

        self.parentHeight = 0

        self.parentWidth = 0



    def arc(self, x, y, radius, startAngle, endAngle, anticlockwise):
        self.pathStr.append(PathElement.arc(x, y, radius, startAngle, endAngle,
                                            anticlockwise, self))


    def beginPath(self):
        self.pathStr.clear()


    def clear(self, width=0, height=0):
        self.pathStr.clear()
        DOM.setInnerHTML(self.parentElement, "")

    def closePath(self):
        self.pathStr.append(PathElement.closePath())


    def createElement(self):
        self.context = VMLContext()
        self.matrix = self.context.matrix
        return self.createParentElement()


    def createParentElement(self):
        self.parentElement = DOM.createElement("div")
        DOM.setStyleAttribute(self.parentElement, "overflow", "hidden")
        return self.parentElement

    def setFont(self, font):
        pass
        # NOT IMPLEMENTED


    def cubicCurveTo(self, cp1x, cp1y, cp2x, cp2y, x, y):
        self.pathStr.append(PathElement.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, x, y, self))
        self.currentX = x
        self.currentY = y


    def drawImage(self, img, *args):

        if isinstance(img, Widget):
            img = img.getElement()
        fullWidth = img.width
        fullHeight = img.height

        if len(args) == 8:
            sourceX = args[0]
            sourceY = args[1]
            sourceWidth = args[2]
            sourceHeight = args[3]
            destX = args[4]
            destY = args[5]
            destWidth = args[6]
            destHeight = args[7]
        elif len(args) == 4:
            sourceX = 0
            sourceY = 0
            sourceWidth = fullWidth
            sourceHeight = fullHeight
            destX = args[0]
            destY = args[1]
            destWidth = args[2]
            destHeight = args[3]
        elif len(args) == 2:
            sourceX = 0
            sourceY = 0
            sourceWidth = fullWidth
            sourceHeight = fullHeight
            destX = args[0]
            destY = args[1]
            destWidth = fullWidth
            destHeight = fullHeight

        vmlStr = [] # JSOStack.getScratchArray()

        vmlStr.append("<v:group style=\"position:absolute;width:10;height:10;")
        dX = self.getCoordX(self.matrix, destX, destY)
        dY = self.getCoordY(self.matrix, destX, destY)

        # If we have a transformation matrix with rotation/scale, we
        # apply a filter
        if self.context.matrix[0] != 1  or  self.context.matrix[1] != 0:

            # We create a padding bounding box to prevent clipping.
            vmlStr.append("padding-right:")
            vmlStr.append(str(self.parentWidth) + "px;")
            vmlStr.append("padding-bottom:")
            vmlStr.append(str(self.parentHeight) + "px;")
            vmlStr.append("filter:progid:DXImageTransform.Microsoft.Matrix(M11='")
            vmlStr.append("" + str(self.matrix[0]))
            vmlStr.append("',")
            vmlStr.append("M12='")
            vmlStr.append("" + str(self.matrix[1]))
            vmlStr.append("',")
            vmlStr.append("M21='")
            vmlStr.append(str(self.matrix[3]))
            vmlStr.append("',")
            vmlStr.append("M22='")
            vmlStr.append(str(self.matrix[4]))
            vmlStr.append("',")
            vmlStr.append("Dx='")
            vmlStr.append(str(math.floor(((dX / 10)))))
            vmlStr.append("',")
            vmlStr.append("Dy='")
            vmlStr.append(str(math.floor(((dY / 10)))))
            vmlStr.append("', SizingMethod='clip');")

        else:
            vmlStr.append("left:")
            vmlStr.append("%dpx;" % int(dX / 10))
            vmlStr.append("top:")
            vmlStr.append("%dpx" % int(dY / 10))


        vmlStr.append("\" coordsize=\"100,100\" coordorigin=\"0,0\"><v:image src=\"")
        vmlStr.append(DOM.getAttribute(img, "src"))
        vmlStr.append("\" style=\"")

        vmlStr.append("width:")
        vmlStr.append(str(int(destWidth * 10)))
        vmlStr.append(";height:")
        vmlStr.append(str(int(destHeight * 10)))
        vmlStr.append(";\" cropleft=\"")
        vmlStr.append(str(sourceX / fullWidth))
        vmlStr.append("\" croptop=\"")
        vmlStr.append(str(sourceY / fullHeight))
        vmlStr.append("\" cropright=\"")
        vmlStr.append(str((fullWidth - sourceX - sourceWidth) / fullWidth))
        vmlStr.append("\" cropbottom=\"")
        vmlStr.append(str((fullHeight - sourceY - sourceHeight) / fullHeight))
        vmlStr.append("\"/></v:group>")

        self.insert("BeforeEnd", ''.join(vmlStr))

    def appendGradient(self, style, shapeStr):
        colorStops = style.gradient.colorStops
        length = len(colorStops)

        shapeStr.append("\" color=\"")
        shapeStr.append(str(colorStops[0].color))
        shapeStr.append("\" color2=\"")
        shapeStr.append(str(colorStops[length - 1].color))
        shapeStr.append("\" type=\"")
        shapeStr.append(style.gradient.type)

        if style.gradient.type == 'gradient':
            #Window.alert(" gdx: " + str(style.gradient.dx) +
            #             " gdy: " + str(style.gradient.dy) +
            #             " gl: " + str(style.gradient.length) +
            #             " ga: " + str(style.gradient.angle))
            # Now add all the color stops
            colors = ""
            for i in range(1, len(colorStops)):
                cs = colorStops[i]
                #Window.alert("color stop offset: " + str(cs.offset))
                stopPosn = cs.offset
                colors += "%d%%" % (int(stopPosn * 100 ))
                colors += str(cs.color) + ","

            shapeStr.append("\" colors=\"")
            shapeStr.append(colors)

        else:
            """
            gradientradial under VML is limited to rectangular gradients
            see http://msdn.microsoft.com/en-us/library/bb264135%28v=vs.85%29.aspx
            so while this code is here, the results will never be what the rest
            of the world would expect - go figure
            """
            minX = self.pathStr.getMinCoordX()
            maxX = self.pathStr.getMaxCoordX()
            minY = self.pathStr.getMinCoordY()
            maxY = self.pathStr.getMaxCoordY()

            dx = maxX - minX
            dy = maxY - minY

            fillLength = math.sqrt((dx * dx) + (dy * dy))

            #Window.alert("fillLength: " + str(fillLength) +
            #             " gdx: " + str(style.gradient.dx) +
            #             " gdy: " + str(style.gradient.dy) +
            #             " gl: " + str(style.gradient.length) +
            #             " ga: " + str(style.gradient.angle) +
            #             " gsr: " + str(style.gradient.startRad) +
            #             " ger: " + str(style.gradient.endRad))

            # need some proper math to calculate the focus position
            focusX = 50
            focusY = 50

            # Now add all the color stops
            colors = ""
            for i in range(1, len(colorStops)):
                cs = colorStops[i]
                #Window.alert("color stop: " + str(cs.offset))
                stopPosn = cs.offset
                #Window.alert("color stopPosn: " + str(stopPosn))
                colors += "%d%%" % (int(stopPosn * 100 ))
                colors += str(cs.color) + ","

            shapeStr.append("\" colors=\"")
            shapeStr.append(colors)

            shapeStr.append("\" focusposition=\"")
            shapeStr.append(str(focusX))
            shapeStr.append("%,")
            shapeStr.append(str(focusY))
            shapeStr.append("%,")

        shapeStr.append("\" angle=\"")
        shapeStr.append(str(style.gradient.angle))

    def appendStroke(self, shapeStr):

        shapeStr.append("<v:stroke opacity=\"")
        shapeStr.append(str(self.context.globalAlpha *
                            self.context.strokeStyle.alpha))
        shapeStr.append("\"")

        if (self.context.strokeStyle.type == 'Gradient'):
            if len(self.context.strokeStyle.gradient.colorStops) > 0:
                self.appendGradient(self.context.strokeStyle, shapeStr)
        else:
            shapeStr.append(" color=\"")
            shapeStr.append(str(self.context.strokeStyle.color))

        shapeStr.append("\" miterlimit=\"")
        shapeStr.append(str(self.context.miterLimit))
        shapeStr.append("\" joinstyle=\"")
        shapeStr.append(self.context.lineJoin)
        shapeStr.append("\" endcap=\"")
        shapeStr.append(self.context.lineCap)

        shapeStr.append("\"></v:stroke>")


    def appendFill(self, shapeStr):

        shapeStr.append("<v:fill opacity=\"")
        shapeStr.append(str(self.context.globalAlpha *
                        self.context.fillStyle.alpha))
        shapeStr.append("\"")

        if (self.context.fillStyle.type == 'Gradient'):
            if len(self.context.fillStyle.gradient.colorStops) > 0:
                self.appendGradient(self.context.fillStyle, shapeStr)
        else:
            shapeStr.append(" color=\"")
            shapeStr.append(str(self.context.fillStyle.color))

        shapeStr.append("\"></v:fill>")


    def fill(self):
        if len(self.pathStr) == 0:
            return

        shapeStr = [] #JSOStack.getScratchArray()
        shapeStr.append("<v:shape style=\"position:absolute;width:10;height:10;\" coordsize=\"100,100")

        shapeStr.append("\" stroked=\"f\" path=\"")
        shapeStr.append(self.pathStr.join())
        shapeStr.append(" e\">")

        self.appendFill(shapeStr)

        shapeStr.append("</v:shape>")

        daStr = ''.join(shapeStr)
        #Window.alert("Fill: " + daStr)
        self.insert(self.context.globalCompositeOperation, daStr)

    def stroke(self):
        if len(self.pathStr) == 0:
            return

        shapeStr = [] #JSOStack.getScratchArray()
        shapeStr.append("<v:shape style=\"position:absolute;")
        shapeStr.append("width:10; height:10;")
        shapeStr.append("\" coordsize=\"100,100")
        shapeStr.append("\" filled=\"f")
        shapeStr.append("\" stroked=\"t")
        shapeStr.append("\" strokeweight=\"")
        shapeStr.append(str(self.context.lineWidth))
        shapeStr.append("px\" path=\"")
        shapeStr.append(self.pathStr.join())
        shapeStr.append(" e\">")

        self.appendStroke(shapeStr)

        shapeStr.append("<v:shape>")

        daStr = ''.join(shapeStr)
        #Window.alert("Stroke: " + daStr)
        self.insert(self.context.globalCompositeOperation, daStr)

    def fillRect(self, x, y, w, h):
        w += x
        h += y
        self.beginPath()
        self.moveTo(x, y)
        self.lineTo(x, h)
        self.lineTo(w, h)
        self.lineTo(w, y)
        self.closePath()
        self.fill()
        self.pathStr.clear()


    def getContext(self):
        return self.context


    def getCoordX(self, matrix, x, y):
        coordX = int(math.floor((math.floor(10 * (matrix[0] * x + matrix[1]
                                * y + matrix[2]) - 4.5))))
        # record current point to derive bounding box of current open path.
        self.pathStr.logCoordX(coordX / 10)
        return coordX


    def getCoordY(self, matrix, x, y):
        coordY = int(math.floor((math.floor(10 * (matrix[3] * x + matrix[4]
                                        * y + matrix[5]) - 4.5))))
        # record current point to derive bounding box of current open path.
        self.pathStr.logCoordY(coordY / 10)
        return coordY


    def getFillStyle(self):
        return self.context.fillStyle


    def getGlobalAlpha(self):
        return self.context.globalAlpha


    def getGlobalCompositeOperation(self):
        if self.context.globalCompositeOperation == DESTINATION_OVER:
            return GWTCanvasConsts.DESTINATION_OVER
        else:
            return GWTCanvasConsts.SOURCE_OVER



    def getLineCap(self):
        if self.context.lineCap == BUTT:
            return GWTCanvasConsts.BUTT

        return self.context.lineCap


    def getLineJoin(self):
        return self.context.lineJoin


    def getLineWidth(self):
        return self.context.lineWidth


    def getMiterLimit(self):
        return self.context.miterLimit


    def getStrokeStyle(self):
        return self.context.strokeStyle


    def lineTo(self, x, y):
        self.pathStr.append(PathElement.lineTo(x, y, self))
        self.currentX = x
        self.currentY = y


    def moveTo(self, x, y):
        self.pathStr.append(PathElement.moveTo(x, y, self))
        self.currentX = x
        self.currentY = y


    def quadraticCurveTo(self, cpx, cpy, x, y):
        cp1x = (self.currentX + 2.0 / 3.0 * (cpx - self.currentX))
        cp1y = (self.currentY + 2.0 / 3.0 * (cpy - self.currentY))
        cp2x = (cp1x + (x - self.currentX) / 3.0)
        cp2y = (cp1y + (y - self.currentY) / 3.0)
        self.pathStr.append(PathElement.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, x, y, self))
        self.currentX = x
        self.currentY = y


    def rect(self, x, y, w, h):
        self.pathStr.append(PathElement.moveTo(x, y, self))
        self.pathStr.append(PathElement.lineTo(x + w, y, self))
        self.pathStr.append(PathElement.lineTo(x + w, y + h, self))
        self.pathStr.append(PathElement.lineTo(x, y + h, self))
        self.pathStr.append(PathElement.closePath())
        self.currentX = x
        self.currentY = y + h


    def restoreContext(self):
        if len(self.contextStack) > 0:
            self.context = self.contextStack.pop()
            self.matrix = self.context.matrix



    def rotate(self, angle):
        s = math.sin(-angle)
        c = math.cos(-angle)
        a = self.matrix[0]
        b = self.matrix[1]
        m1 = a * c
        m2 = b * s
        self.matrix[0] = m1 - m2
        m1 = a * s
        m2 = b * c
        self.matrix[1] = m1 + m2
        a = self.matrix[3]
        b = self.matrix[4]
        m1 = a * c
        m2 = b * s
        self.matrix[3] = m1 - m2
        m1 = a * s
        m2 = b * c
        self.matrix[4] = m1 + m2


    def saveContext(self):
        self.contextStack.append(self.context)
        self.context = VMLContext(self.context)
        self.matrix = self.context.matrix


    def scale(self, x, y):
        self.context.arcScaleX *= x
        self.context.arcScaleY *= y
        self.matrix[0] *= x
        self.matrix[1] *= y
        self.matrix[3] *= x
        self.matrix[4] *= y


    def setBackgroundColor(self, element, color):
        DOM.setStyleAttribute(element, "backgroundColor", color)


    def setCoordHeight(self, elem, height):
        DOM.setElemAttribute(elem, "width", int(height))
        self.clear(0, 0)


    def setCoordWidth(self, elem, width):
        DOM.setElemAttribute(elem, "width", int(width))
        self.clear(0, 0)


    def setCurrentX(self, currentX):
        self.currentX = currentX


    def setCurrentY(self, currentY):
        self.currentY = currentY


    #def setFillStyle(self, gradient):
    #    Window.alert("fillStyle gradient: " + str(gradient))
    #    self.context.fillGradient = gradient


    def setFillStyle(self, fillStyle):
        #Window.alert(str(fillStyle))

        self.context.fillStyle = VMLStyle()

        if isinstance(fillStyle, CanvasGradientImplIE6):
            self.context.fillStyle.type = 'Gradient'
            self.context.fillStyle.gradient = fillStyle
            #Window.alert("gradient fillstyle: " +
            #             str(len(self.context.fillStyle.gradient.colorStops)))
        else:
            fillStyle = str(fillStyle).strip()
            if fillStyle.startswith("rgba("):
                end = fillStyle.find(")", 12)
                if end > -1:
                    guts = fillStyle[5:end].split(",")
                    if len(guts) == 4:
                        self.context.fillStyle.alpha = float(guts[3])
                        self.context.fillStyle.color = \
                         "rgb(" + guts[0] + "," + guts[1] + "," + guts[2] + ")"
            else:
                self.context.fillStyle.color = fillStyle


    #def setStrokeStyle(self, gradient):
    #    self.context.strokeGradient = gradient


    def setStrokeStyle(self, strokeStyle):
        self.context.strokeStyle = VMLStyle()

        if isinstance(strokeStyle, CanvasGradientImplIE6):
            self.context.strokeStyle.type = 'Gradient'
            self.context.strokeStyle.gradient = strokeStyle
        else:
            strokeStyle = str(strokeStyle).strip()
            if strokeStyle.startswith("rgba("):
                end = strokeStyle.find(")", 12)
                if end > -1:
                    guts = strokeStyle[5:end].split(",")
                    if len(guts) == 4:
                        self.context.stokeStyle.alpha = float(guts[3])
                        self.context.strokeStyle.color = \
                         "rgb(" + guts[0] + "," + guts[1] + "," + guts[2] + ")"
            else:
                self.context.strokeStyle.color = strokeStyle


    def setGlobalAlpha(self, globalAlpha):
        self.context.globalAlpha = globalAlpha


    def setGlobalCompositeOperation(self, gco):
        gco = gco.strip()
        if gco.lower == GWTCanvasConsts.SOURCE_OVER:
            self.context.globalCompositeOperation = SOURCE_OVER
        elif gco.lower == GWTCanvasConsts.DESTINATION_OVER:
            self.context.globalCompositeOperation = DESTINATION_OVER



    def setLineCap(self, lineCap):
        if lineCap.strip().lower == GWTCanvasConsts.BUTT:
            self.context.lineCap = BUTT
        else:
            self.context.lineCap = lineCap



    def setLineJoin(self, lineJoin):
        self.context.lineJoin = lineJoin


    def setLineWidth(self, lineWidth):
        self.context.lineWidth = lineWidth


    def setMiterLimit(self, miterLimit):
        self.context.miterLimit = miterLimit

    def setParentElement(self, g):
        self.parentElement = g


    def setPixelHeight(self, elem, height):
        DOM.setStyleAttribute(elem, "height", str(height) + "px")
        self.parentHeight = height


    def setPixelWidth(self, elem, width):
        DOM.setStyleAttribute(elem, "width", str(width) + "px")
        self.parentWidth = width


    def strokeRect(self, x, y, w, h):
        w += x
        h += y
        self.beginPath()
        self.moveTo(x, y)
        self.lineTo(x, h)
        self.lineTo(w, h)
        self.lineTo(w, y)
        self.closePath()
        self.stroke()
        self.pathStr.clear()


    def transform(m11, m12, m21, m22, dx, dy):
        a = self.matrix[0]
        b = self.matrix[1]
        self.matrix[0] = a * m11 + b * m21
        self.matrix[1] = a * m12 + b * m22
        self.matrix[2] += a * dx + b * dy
        a = self.matrix[3]
        b = self.matrix[4]
        self.matrix[3] = a * m11 + b * m21
        self.matrix[4] = a * m12 + b * m22
        self.matrix[5] += a * dx + b * dy


    def translate(self, x, y):
        self.matrix[2] += self.matrix[0] * x + self.matrix[1] * y
        self.matrix[5] += self.matrix[3] * x + self.matrix[4] * y


    def insert(self, gco, html):
        self.parentElement.insertAdjacentHTML(gco, html)


    """
    THERE STILL NEEDS TO BE SOMETHING THAT ALLOWS FOR FONT CONTROL

    #// Internal text style cache
    fontStyleCache = {}


    def processFontStyle(self, styleString):
        if fontStyleCache[styleString]:
            return fontStyleCache[styleString]

        el = document.createElement('div')
        style = el.style
        try:
            style.font = styleString
        except ex:
            #// Ignore failures to set to invalid font.

        return fontStyleCache[styleString] =:
            style: style.fontStyle || DEFAULT_STYLE.style,
            variant: style.fontVariant || DEFAULT_STYLE.variant,
            weight: style.fontWeight || DEFAULT_STYLE.weight,
            size: style.fontSize || DEFAULT_STYLE.size,
            family: style.fontFamily || DEFAULT_STYLE.family

    def getComputedStyle(style, element):
        computedStyle = {}

        for p in style:
            computedStyle[p] = style[p]

        #// Compute the size
        canvasFontSize = parseFloat(element.currentStyle.fontSize)
        fontSize = parseFloat(style['size'])

        if typeof style['size'] == 'number':
            computedStyle['size'] = style['size']
        elif style['size']['indexOf('px') != -1:
            computedStyle['size'] = fontSize
        elif style['size']['indexOf('em') != -1:
            computedStyle['size'] = canvasFontSize * fontSize
        elif(style['size']['indexOf('%') != -1:
            computedStyle['size'] = (canvasFontSize / 100) * fontSize
        elif style['size']['indexOf('pt') != -1:
            computedStyle['size'] = fontSize / .75
        else:
            computedStyle['size'] = canvasFontSize

        #// Different scaling between normal text and VML text.
        #// This was found using trial and error to get the same size
        #// as non VML text.
        computedStyle['size'] *= 0.981

        return computedStyle
    """

    def buildStyleString(self, style):
        return style['style'] + ' ' + style['variant'] + ' ' + \
               style['weight'] + ' ' + str(style['size']) + 'px ' + \
               style['family']

    def encodeHtmlAttribute(self, s):
        e = s.replace('&', '&amp;')
        return e.replace('"', '&quot;')

    def drawText_(self, text, x, y, maxWidth, stroke):
        delta = 1000
        left = 0
        right = delta
        offsetX = 0
        offsetY = 0

        DEFAULT_STYLE = {
            'style': 'normal',
            'variant': 'normal',
            'weight': 'normal',
            'size': 10,
            'family': 'sans-serif'}

        """
        fontStyle = getComputedStyle(processFontStyle(self.font),
                                     self.element_)

        fontStyleString = buildStyleString(fontStyle)

        elementStyle = self.element_.currentStyle
        textAlign = self.textAlign.toLowerCase()

        if textAlign == 'left' || textAlign == 'center' || \
                textAlign == 'right':
            pass
        elif textAlign == 'end':
            if elementStyle.direction == 'ltr':
                textAlign = 'right'
            else:
                textAlign = 'left'
        elif textAlign == 'start':
            if elementStyle.direction == 'rtl':
                textAlign = 'right'
            else:
                textAlign = 'left'
        else:
            textAlign = 'left'

        #// 1.75 is an arbitrary number, as there is no info about
        #// the text baseline
        if textBaseline == 'hanging' || textBaseline == 'top':
            offsetY = fontStyle.size / 1.75
        elif textBaseline == 'middle':
            pass
        else:
            # default:
            # if textBaseline == null:
            # if textBaseline == 'alphabetic':
            # if textBaseline == 'ideographic':
            # if textBaseline == 'bottom':
            offsetY = -fontStyle.size / 2.25
        if textAlign == 'right':
            left = delta
            right = 0.05
        elif textAlign == 'center':
            left = right = delta / 2
        """
        fontStyleString = self.buildStyleString(DEFAULT_STYLE)
        textAlign = 'left'

        dX = self.getCoordX(self.matrix, x + offsetX, y + offsetY)
        dY = self.getCoordY(self.matrix, x + offsetX, y + offsetY)

        #Window.alert("dX: " + str(dX) + " dY: " + str(dY))

        lineStr = [] #JSOStack.getScratchArray()

        lineStr.append('<v:line from="')
        lineStr.append(str(-left))
        lineStr.append(' 0" to="',)
        lineStr.append(str(right))
        lineStr.append(' 0" ')
        lineStr.append(' coordsize="100 100" coordorigin="0 0"')
        lineStr.append('" style="position:absolute;width:1px;height:1px"')
        if stroke:
            lineStr.append(' filled="f" stroked="t">')
            self.appendStroke(lineStr)
        else:
            lineStr.append(' filled="t" stroked="f">')
            self.appendFill(lineStr)

        skewM = str(self.matrix[0]) + ',' + str(self.matrix[1]) + ',' + \
                str(self.matrix[3]) + ',' + str(self.matrix[4]) + ',0,0'
        #Window.alert(skewM)

        skewOffset = str(math.floor(dX / 10)) + ',' + \
                     str(math.floor(dY / 10))

        lineStr.append('<v:skew on="t" matrix="')
        lineStr.append(skewM)
        lineStr.append('" ')
        lineStr.append(' offset="')
        lineStr.append(skewOffset)
        lineStr.append('" origin="')
        lineStr.append(str(left))
        lineStr.append(' 0" />')

        lineStr.append('<v:path textpathok="true" />')
        lineStr.append('<v:textpath on="true" string="')
        lineStr.append(self.encodeHtmlAttribute(text))
        lineStr.append('" style="v-text-align:')
        lineStr.append(textAlign)
        lineStr.append(';font:')
        lineStr.append(self.encodeHtmlAttribute(fontStyleString))
        lineStr.append('" /></v:line>')

        daStr = ''.join(lineStr)
        #Window.alert("Text: " + daStr)
        self.insert(self.context.globalCompositeOperation, daStr)

    def fillText(self, text, x, y, maxWidth=None):
        self.drawText_(text, x, y, maxWidth, False)

    def strokeText(self, text, x, y, maxWidth=None):
        self.drawText_(text, x, y, maxWidth, True)

    """
    def measureText(self, text):
        if !self.textMeasureEl_:
            s = '<span style="position:absolute' +
                    'top:-20000px;left:0;padding:0;margin:0;border:none' +
                    'white-space:pre"></span>'
            self.element_.insertAdjacentHTML('beforeEnd', s)
            self.textMeasureEl_ = self.element_.lastChild

        doc = self.element_.ownerDocument
        self.textMeasureEl_.innerHTML = ''
        self.textMeasureEl_.style.font = self.font
        #// Don't use innerHTML or innerText because they allow
        #// markup/whitespace.
        self.textMeasureEl_.appendChild(doc.createTextNode(text))
        return:width: self.textMeasureEl_.offsetWidth}
    """
