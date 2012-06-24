""" raphael.py

    This Python module is a Pyjamas wrapper around the Raphael SVG graphics
    library.

    The Raphael wrapper was initially written by Erik Westra
    (ewestra at gmail dot com) and extended by Juergen Schackmann
    (juergen dot schackmann at googlemail dot com)


Missing/Todo (in order priority):
- Zooming and Panning
- Callback for Animate Function
- Animavewith Function (added by myself, but not working at the moment)
- Implement all functions for the Connection Element
- Merge setAttrs and setAttr into one with args, kwargs like params

"""

from pyjamas.ui.Widget import Widget
from pyjamas import DOM
from pyjamas import Window
from __pyjamas__ import JS

#############################################################################
class RaphaelEventHandler(object):
    def __init__(self,element):
        self._listeners = {'click'      : [],
                           'mousedown'  : [],
                           'mouseup'    : [],
                           'mousemove'  : [],
                           'mouseenter' : [],
                           'mouseleave' : [],
                           'mouseout'   : [],
                           'dblclick'    : [],
                           'contextmenu': []}

        self._sender = {'click'      : [],
                           'mousedown'  : [],
                           'mouseup'    : [],
                           'mousemove'  : [],
                           'mouseenter' : [],
                           'mouseleave' : [],
                           'mouseout'   : [],
                           'dblclick'    : [],
                           'contextmenu': []}

        onClick      = getattr(self, "_onClick")
        onMouseDown  = getattr(self, "_onMouseDown")
        onMouseUp    = getattr(self, "_onMouseUp")
        onMouseMove  = getattr(self, "_onMouseMove")
        onMouseEnter = getattr(self, "_onMouseEnter")
        onMouseLeave = getattr(self, "_onMouseLeave")
        onMouseOut   = getattr(self, "_onMouseOut")
        onDblClick    = getattr(self, "_onDblClick")
        onContextMenu =  getattr(self, "_onContextMenu")
        JS("""
           this['_event_element']=@{{element}};
           this['_event_element']['onclick']      = @{{onClick}};
           this['_event_element']['onmousedown']  = @{{onMouseDown}};
           this['_event_element']['onmouseup']    = @{{onMouseUp}};
           this['_event_element']['onmousemove']  = @{{onMouseMove}};
           this['_event_element']['onmouseenter'] = @{{onMouseEnter}};
           this['_event_element']['onmouseout']   = @{{onMouseOut}};
           this['_event_element']['onmouseleave'] = @{{onMouseLeave}};
           this['_event_element']['ondblclick']   = @{{onDblClick}};
           this['_event_element']['oncontextmenu']= @{{onContextMenu}};
        """)

    def addListener(self, type, listener, sender=None):
        """ Add a listener function to this element.

            The parameters are as follows:

                'type'

                    The type of event to listen out for.  One of:

                        "click"
                        "mousedown"
                        "mouseup"
                        "mousemove"
                        "mouseenter"
                        "mouseleave"
                        "mouseleave"

                'listener'

                    A Python callable object which accepts two parameters: the
                    RaphaelElement object that was clicked on, and the event
                    object.

            The given listener function will be called whenever an event of the
            given type occurs.
        """
        self._listeners[type].append(listener)
        self._sender[type].append(sender)

    def removeListener(self, type, listener):
        """ Remove a previously-defined listener function.
        """
        i=self._listeners[type].index(listener)

        self._sender[type].delete(i)
        self._listeners[type].remove(listener)

    def _onClick(self, event):
        """ Respond to a mouse-click event.
        """
        listeners = self._listeners['click']
        sender = self._sender['click']
        for listener,send in zip(listeners,sender):
            listener(send or self, event)


    def _onMouseDown(self, event):
        """ Respond to a mouse-down event.
        """
        listeners = self._listeners['mousedown']
        sender = self._sender['mousedown']
        for listener,send in zip(listeners,sender):
            listener(send or self, event)


    def _onMouseUp(self, event):
        """ Respond to a mouse-up event.
        """
        listeners = self._listeners['mouseup']
        sender = self._sender['mouseup']
        for listener,send in zip(listeners,sender):
            listener(send or self, event)


    def _onMouseMove(self, event):
        """ Respond to a mouse-move event.
        """
        listeners = self._listeners['mousemove']
        sender = self._sender['mousemove']
        for listener,send in zip(listeners,sender):
            listener(send or self, event)


    def _onMouseEnter(self, event):
        """ Respond to a mouse-enter event.
        """
        listeners = self._listeners['mouseenter']
        sender = self._sender['mouseenter']
        for listener,send in zip(listeners,sender):
            listener(send or self, event)


    def _onMouseLeave(self, event):
        """ Respond to a mouse-leave event.
        """
        listeners = self._listeners['mouseleave']
        sender = self._sender['mouseleave']
        for listener,send in zip(listeners,sender):
            listener(send or self, event)

    def _onMouseOut(self, event):
        """ Respond to a mouse-out event.
        """
        listeners = self._listeners['mouseout']
        sender = self._sender['mouseout']
        for listener,send in zip(listeners,sender):
            listener(send or self, event)

    def _onDblClick(self, event):
        """ Respond to a Double Click event.
        """
        listeners = self._listeners['dblclick']
        sender = self._sender['mouseout']
        for listener,send in zip(listeners,sender):
            listener(send or self, event)

    def _onContextMenu(self,event):
        """ Respond to a Context Menue event.
        """
        listeners = self._listeners['contextmenu']
        sender = self._sender['contextmenu']
        for listener,send in zip(listeners,sender):
            listener(send or self, event)


class Raphael(Widget,RaphaelEventHandler):
    """ A Pyjamas wrapper around the Raphael canvas object.
    """
    def __init__(self, width, height):
        """ Standard initialiser.

            'width' and 'height' are the dimensions to use for the canvas, in
            pixels.
        """
        Widget.__init__(self)
        #self.getParent()

        element = DOM.createDiv()
        self.setElement(element)
        self.setPixelSize(width, height)
        JS("""
           this['_canvas'] = $wnd['Raphael'](@{{element}}, @{{width}}, @{{height}});
        """)
        RaphaelEventHandler.__init__(self,self.element)

    def getCanvas(self):
        """ Return our Raphael canvas object.

            This can be used to directly access any Raphael functionality which
            has not been implemented by this wrapper module.  You'll probably
            never need to use it, but it's here just in case.
        """
        return self._canvas


    def setSize(self, width, height):
        """ Change the dimensions of the canvas.
        """
        JS("""
           this['_canvas']['setSize'](@{{width}}, @{{height}});
        """)


    def getColor(self, brightness=None):
        """ Return the next colour to use in the spectrum.
        """
        JS("""
           @{{colour}} = this['_canvas']['getColor']();
        """)
        return colour


    def resetColor(self):
        """ Reset getColor() so that it will start from the beginning.
        """
        JS("""
           this['_canvas']['getColor']()['reset']();
        """)


    def circle(self, x, y, radius):
        """ Create and return a circle element.

            The circle will be centred around (x,y), and will have the given
            radius.

            We return a RaphaelElement object representing the circle.
        """
        JS("""
           this['_element'] = this['_canvas']['circle'](@{{x}}, @{{y}}, @{{radius}});
           this['_canvas']['safari']();
        """)
        return RaphaelElement(self._element)


    def rect(self, x, y, width, height, cornerRadius=0):
        """ Create and return a rectangle element.

            The rectangle will have its top-left corner at (x,y), and have the
            given width and height.  If 'cornerRadius' is specified, the
            rectangle will have rounded corners with the given radius.

            We return a RaphaelElement object representing the rectangle.
        """
        JS("""
           this['_element'] = this['_canvas']['rect'](@{{x}}, @{{y}}, @{{width}}, @{{height}},
                                             @{{cornerRadius}});
        """)
        return RaphaelElement(self._element)


    def ellipse(self, x, y, xRadius, yRadius):
        """ Create and return an ellipse element.

            The ellipse will be centred around (x,y), and will have the given
            horizontal and vertical radius.

            We return a RaphaelElement object representing the ellipse.
        """
        JS("""
           this['_element'] = this['_canvas']['ellipse'](@{{x}}, @{{y}}, @{{xRadius}}, @{{yRadius}});
        """)
        return RaphaelElement(self._element)


    def image(self, src, x, y, width, height):
        """ Create and return an image element.

            The image will use 'src' as the URI to read the image data from.
            The top-left corner of the image will be at (x,y), and the image
            element will have the given width and height.

            We return a RaphaelElement object representing the image.
        """
        JS("""
           this['_element'] = this['_canvas']['image'](@{{src}}, @{{x}}, @{{y}}, @{{width}}, @{{height}});
        """)
        return RaphaelElement(self._element)


    def set(self):
        """ Create and return a set element.

            This can be used to group elements together and operate on these
            elements as a unit.

            We return a RaphaelSetElement representing the set.
        """
        JS("""
           this['_element'] = this['_canvas']['set']();
        """)
        return RaphaelSetElement(self._element)


    def text(self, x, y, text):
        """ Create and return a text element.

            The element will be placed at (x,y), and will display the given
            text.  Note that you can embed newline ("\n") characters into the
            text to force line breaks.

            We return a RaphaelElement representing the text.
        """
        JS("""
           this['_element'] = this['_canvas']['text'](@{{x}}, @{{y}}, @{{text}});
        """)
        return RaphaelElement(self._element)


    def path(self,  data=None, attrs=None,):
        """ Create and return a path object.

            If 'attrs' is defined, it should be a dictionary mapping attribute
            names to values for the new path object.  If 'data' is not None, it
            should be a string containing the path data, in SVG path string
            format.

            We return a RaphaelPathElement representing the path.
        """
        if data != None:
            JS("""
               this['_element'] = this['_canvas']['path'](@{{data}});
            """)
        else:
            JS("""
               this['_element'] = this['_canvas']['path']("");
            """)

        if attrs != None:
            for attr in attrs.keys():
                value = attrs[attr]
                JS("""
                    this['_element']['attr'](@{{attr}}, @{{value}});
                """)
        return RaphaelPathElement(self._element)

    def connection(self,obj1,obj2=None,line=None,bg=None,cp1=None,cp2=None,p1=None,p2=None):
        line_path=self.path(None,{'stroke-width':5})
        bg_path=self.path(None,{'stroke-width':5})
        return RaphaelConnectionElement(line_path,bg_path,obj1,obj2,line,bg,cp1,cp2,p1,p2)



class RaphaelElement(object,RaphaelEventHandler):
    """ Wrapper object for a Raphael element.

        Note that these objects are created by the appropriate methods within
        the Raphael object; you should never need to initialise one of these
        objects yourself.
    """
    def __init__(self, raphaelElement):
        """ Standard initialiser.

            'raphaelElement' is the raphael element that we are wrapping.
        """
        self._element   = raphaelElement
        RaphaelEventHandler.__init__(self,self._element.node)

    def getElement(self):
        """ Return the DOM element we are wrapping.
        """
        return self._element


    def remove(self):
        """ Remove this element from the canvas.

            You can't use the element after you call this method.
        """
        JS("""
           this['_element']['remove']();
        """)


    def hide(self):
        """ Make this element invisible.
        """
        JS("""
           this['_element']['hide']();
        """)


    def show(self):
        """ Make this element visible.
        """
        JS("""
           this['_element']['show']();
        """)


    def rotate(self, angle, cx, cy=None):
        """ Rotate the element by the given angle.

            This can be called in two different ways:

                element.rotate(angle, isAbsolute)

                   where 'angle' is the angle to rotate the element by, in
                   degrees, and 'isAbsolute' specifies it the angle is relative
                   to the previous position (False) or if it is the absolute
                   angle to rotate the element by (True).

            or:

                element.rotate(angle, cx, cy):

                    where 'angle' is the angle to rotate the element by, in
                    degrees, and 'cx' and 'cy' define the origin around which
                    to rotate the element.
        """
        if cy == None:
            isAbsolute = cx
            JS("""
               this['_element']['rotate'](@{{angle}}, @{{isAbsolute}});
            """)
        else:
            JS("""
               this['_element']['rotate'](@{{angle}}, @{{cx}}, @{{cy}});
            """)


    def translate(self, dx, dy):
        """ Move the element around the canvas by the given number of pixels.
        """
        JS("""
           this['_element']['translate'](@{{dx}}, @{{dy}});
        """)


    def scale(self, xtimes, ytimes):
        """ Resize the element by the given horizontal and vertical multiplier.
        """
        JS("""
           this['_element']['scale'](@{{xtimes}}, @{{ytimes}});
        """)


    def setAttr(self, attr, value):
        """ Set the value of a single attribute for this element.

            The following attributes are currently supported:

                cx number
                cy number
                fill colour
                fill-opacity number
                font string
                font-family string
                font-size number
                font-weight string
                gradient object|string
                        "‹angle›-‹colour›[-‹colour›[:‹offset›]]*-‹colour›"
                height number
                opacity number
                path pathString
                r number
                rotation number
                rx number
                ry number
                scale CSV
                src string (URL)
                stroke colour
                stroke-dasharray string ['-', '.', '-.', '-..', '. ', '- ',
                                         '--', '- .', '--.', '--..']
                stroke-linecap string ['butt', 'square', 'round', 'miter']
                stroke-linejoin string ['butt', 'square', 'round', 'miter']
                stroke-miterlimit number
                stroke-opacity number
                stroke-width number
                translation CSV
                width number
                x number
                y number

            Please refer to the SVG specification for an explanation of these
            attributes and how to use them.
        """
        JS("""
           this['_element']['attr'](@{{attr}}, @{{value}});
        """)


    def setAttrs(self, attrs):
        """ Set the value of multiple attributes at once.

            'attrs' should be a dictionary mapping attribute names to values.

            The available attributes are listed in the description of the
            setAttr() method, above.
        """
        for attr,value in attrs.items():
            JS("""
               this['_element']['attr'](@{{attr}}, @{{value}});
            """)


    def getAttr(self, attr):
        """ Return the current value for the given attribute.
        """
        JS("""
           var value = this['_element']['attr'](@{{attr}});
        """)
        return value


    def animate(self, attrs, duration):
        """ Linearly change one or more attributes over a given timeframe.

            'attrs' should be a dictionary mapping attribute names to values,
            and 'duration' should be how long to run the animation for (in
            milliseconds).

            Only the following attributes can be animated:

                cx number
                cy number
                fill colour
                fill-opacity number
                font-size number
                height number
                opacity number
                path pathString
                r number
                rotation number
                rx number
                ry number
                scale CSV
                stroke colour
                stroke-opacity number
                stroke-width number
                translation CSV
                width number
                x number
                y number

            Note that the use of a callback function is not yet supported
            within the Raphael wrapper, even though Raphael itself supports it.
        """
        JS("""
           var jsAttrs = {};
        """)
        for attr,value in attrs.items():
            JS("""
               jsAttrs[@{{attr}}] = @{{value}};
            """)

        JS("""
           this['_element']['animate'](jsAttrs, @{{duration}});
        """)

    def animatewith(self, element, attrs, duration):
        JS("""
           var jsAttrs = {};
        """)
        otherElement=element.getElement()
        for attr,value in attrs.items():
            JS("""
               jsAttrs[@{{attr}}] = @{{value}};
            """)

        JS("""
           this['_element']['animate'](@{{otherElement}},@{{jsAttrs}}, @{{duration}});
        """)

    def getBBox(self):
        """ Return the bounding box for this element.

            We return a dictionary with 'x', 'y', 'width' and 'height'
            elements.
        """
        x=0
        y=0
        width=0
        height=0
        JS("""
           var bounds = this['_element']['getBBox']();
           @{{x}} = bounds['x'];
           @{{y}} = bounds['y'];
           @{{width}} = bounds['width'];
           @{{height}} = bounds['height'];
        """)
        return {'x'      : x,
                'y'      : y,
                'width'  : width,
                'height' : height}


    def toFront(self):
        """ Move the element in front of all other elements on the canvas.
        """
        JS("""
           this['_element']['toFront']();
        """)


    def toBack(self):
        """ Move the element behind all the other elements on the canvas.
        """
        JS("""
           this['_element']['toBack']();
        """)


    def insertBefore(self, element):
        """ Move this element so that it appears in front of the given element.

            'element' should be a RaphaelElement object.
        """
        otherElement = element.getElement()
        JS("""
           this['_element']['insertBefore'](@{{otherElement}});
        """)


    def insertAfter(self, element):
        """ Move this element so that it appears behind the given element.
        """
        otherElement = element.getElement()
        JS("""
           this['_element']['insertAfter'](@{{otherElement}});
        """)

    def drag(self,move,start,up):
        onMove  = getattr(self, "_onMove")
        onStart = getattr(self, "_onStart")
        onUp    = getattr(self, "_onUp")

        self.onMoveFunction=move
        self.onStartFunction=start
        self.onUpFunction=up

        JS("""
           this['_element']['drag'](@{{onMove}},@{{onStart}},@{{onUp}});
        """)

    #todo
    #check these args and see if they are correct
    def _onMove(self,dx,dy,x,y,event):
        self.onMoveFunction(self,dx,dy,x,y)

    def _onStart(self,x,y,event):
        self.onStartFunction(self,x,y)

    def _onUp(self, event):
        self.onUpFunction(self, event)

#############################################################################

class RaphaelSetElement(RaphaelElement):
    """ A RaphaelElement that represents a set of elements.
    """

    def __init__(self, raphaelElement):
        """
        Needs a custom init, since the event handling does not work on set
        (since no element is created for Set)
        """
        self._element   = raphaelElement
        self.raphael_elements=[]

    def add(self, element):
        """ Add an element to this set.
        """
        self.raphael_elements.append(element)
        otherElement = element.getElement()
        JS("""
           this['_element']['push'](@{{otherElement}});
        """)

    def addListener(self,type,listener):
        for element in self.raphael_elements:
            element.addListener(type,listener,self)


    def removeListener(self,type,listener):
        for element in self.raphael_elements:
            element.removeListener(type,listener)

#############################################################################

class _DockConnection(object):
    NORTH=0
    EAST=3
    SOUTH=1
    WEST=2

class DOCK_CONNECTION(object):
    NORTH=0
    EAST=3
    SOUTH=1
    WEST=2

COUNTER_MAP={0:1,1:0,2:3,3:2}

class RaphaelConnectionElement(RaphaelElement):
    '''
    The connection logic is taken from the Graffle Example at the Raphael Examples
    '''

    def __init__(self,line_path, bg_path,obj1=None,obj2=None, line={},bg={}, cp1=None, cp2=None,p1=None,p2=None):
        self.obj1=obj1
        self.obj2=obj2
        self.line_path=line_path
        self.bg_path=bg_path
        self.cp1=cp1
        self.cp2=cp2
        self.p1=p1
        self.p2=p2

        self.draw()

        line=line or {}
        bg=bg or {}
        if line:
            self.setLineAttrs(line)
        if bg:
            self.setBackGroundAttrs(bg)



    def _getPath(self):
        p=[]
        d={}
        dis=[]
        #cp_map={0:0,90:3,180:1,270:2}
        #counter_map={0:1,1:0,2:3,3:2}
        if self.obj1 and self.obj2:
            bb1=self.obj1.getBBox()
            bb2=self.obj2.getBBox()
            p=[ {'x':bb1['x']+bb1['width']/2,'y':bb1['y']-1},               #0:  object 1, Top,Middle
                {'x':bb1['x']+bb1['width']/2,'y':bb1['y']+bb1['height']+1}, #1:  object 1, Bottom,Middle
                {'x':bb1['x']-1,             'y':bb1['y']+bb1['height']/2}, #2:  object 1, Left, Middle
                {'x':bb1['x']+bb1['width']+1,'y':bb1['y']+bb1['height']/2}, #3:  object 1, Right, Middle
                {'x':bb2['x']+bb2['width']/2,'y':bb2['y']-1},               #4/0:object 2, Top, Middle
                {'x':bb2['x']+bb2['width']/2,'y':bb2['y']+bb2['height']+1}, #5/1:object 2, Bottom, Middle
                {'x':bb2['x']-1,             'y':bb2['y']+bb2['height']/2}, #6/2:object 2, Left, Middle
                {'x':bb2['x']+bb2['width']+1,'y':bb2['y']+bb2['height']/2}] #7/3:object 2, Right, Middle

        if self.obj1 and not self.obj2:
            bb1=self.obj1.getBBox()
            p=[ {'x':bb1['x']+bb1['width']/2,'y':bb1['y']-1},               #0:  object 1, Top,Middle
                {'x':bb1['x']+bb1['width']/2,'y':bb1['y']+bb1['height']+1}, #1:  object 1, Bottom,Middle
                {'x':bb1['x']-1,             'y':bb1['y']+bb1['height']/2}, #2:  object 1, Left, Middle
                {'x':bb1['x']+bb1['width']+1,'y':bb1['y']+bb1['height']/2}]#3:  object 1, Right, Middle

        if not self.obj1 and self.obj2:
            bb2=self.obj2.getBBox()
            p=[ {'x':bb2['x']+bb2['width']/2,'y':bb2['y']-1},               #4/0:object 2, Top, Middle
                {'x':bb2['x']+bb2['width']/2,'y':bb2['y']+bb2['height']+1}, #5/1:object 2, Bottom, Middle
                {'x':bb2['x']-1,             'y':bb2['y']+bb2['height']/2}, #6/2:object 2, Left, Middle
                {'x':bb2['x']+bb2['width']+1,'y':bb2['y']+bb2['height']/2}] #7/3:object 2, Right, Middle
        if not self.p1 and not self.p2 and (not self.cp1 or not self.cp2):
            for i in range(0,3):
                for j in range(4,7):
                    dx=abs(p[i]['x']-p[j]['x'])
                    dy=abs(p[i]['y']-p[j]['y'])
                    if ((i==j-4) or (((i<>3 and j<>6) or p[i]['x'] < p[j]['x']) and ((i<>2 and j<>7) or p[i]['x'] > p[j]['x']) and ((i<>0 and j<>5) or p[i]['y'] > p[j]['y']) and ((i<>1 and j<>4) or p[i]['y'] < p[j]['y'] ))):
                        dis.append(dy+dy)
                        d[dis[len(dis)-1]]=[i,j]

            if len(dis)==0:
                res=[0,4]
            else:
                res=d[min(dis)]
            x1=p[res[0]]['x']
            y1=p[res[0]]['y']
            x4=p[res[1]]['x']
            y4=p[res[1]]['y']
        else:
            if self.cp1:
                x1,y1=p[self.cp1]['x'],p[self.cp1]['y']
                res1=self.cp1
            else:
                x1=self.p1[0]
                y1=self.p1[1]
                res1=None
            if self.cp2:
                x4,y4=p[self.cp2+4]['x'],p[self.cp2+4]['y']
                res2=self.cp2+4
            else:
                x4=self.p2[0]
                y4=self.p2[1]
                res2=None
            if res1==None and res2==None:
                res1=0
                res2=4
            elif res1<>None and res2==None:
                if res1<4:
                    res2=COUNTER_MAP[res1]+4
                else:
                    res2=COUNTER_MAP[res1]-4
            elif res1==None and res2<>None:
                if res2<4:
                    res1=COUNTER_MAP[res2]+4
                else:
                    res1=COUNTER_MAP[res2]-4
            res=[res1,res2]
        dx=max(abs(x1-x4)/2,10)
        dy=max(abs(y1-y4)/2,10)
        x2=[x1,x1,x1-dx,x1+dx][res[0]]
        y2=[y1-dy,y1+dy,y1,y1][res[0]]
        x3=[0,0,0,0,x4,x4,x4-dx,x4+dx][res[1]]
        y3=[0,0,0,0,y1+dy,y1-dy,y4,y4][res[1]]
        return ','.join(['M',str(x1),str(y1),'C',str(x2),str(y2),str(x3),str(y3),str(x4),str(y4)])


    def draw(self,p1=None,p2=None):
        self.p1=p1 or self.p1
        self.p2=p2 or self.p2
        path=self._getPath()
        self.line_path.setAttr('path',path)
        self.bg_path.setAttr('path',path)

    def setLineAttrs(self,attrs):
        self.line_path.setAttrs(attrs)

    def setBackGroundAttrs(self,attrs):
        self.bg_path.setAttrs(attrs)

    def toFront(self):
        self.line_path.toFront()
        self.bg_path.toFront()

    def toBack(self):
        self.line_path.toBack()
        self.bg_path.toBack()

    def remove(self):
        self.line_path.remove()
        self.bg_path.remove()

    def addListener(self,type,listener):
        self.line_path.addListener(type,listener,self)
        self.bg_path.addListener(type,listener,self)

    def removeListener(self,type,listener):
        self.line_path.removeListener(type,listener)
        self.bg_path.removeListener(type,listener)

###########################################################################

class RaphaelPathElement(RaphaelElement):
    """ A RaphaelElement that represents a path.

        The commented out methods seem to rely on an old beta version of
        the Raphael API. If considered helpful, they can certainly be
        replicated with currently available methods.
    """
    pass
##    def absolutely(self):
##        """ Tell the path to treat all subsequent units as absolute ones.
##
##            Coordinates are absolute by default.
##        """
##        JS("""
##            this['_element']['absolutely']();
##        """)
##        return self
##
##
##    def relatively(self):
##        """ Tell the path to treat all subsequent units as relative ones.
##
##            Coordinates are absolute by default.
##        """
##        JS("""
##            this['_element']['relatively']();
##        """)
##        return self
##
##
##    def moveTo(self, x, y):
##        """ Move the drawing point to the given coordinates.
##        """
###        JS("""
###            this['_element']['moveTo'](@{{x}}, @{{y}});
###        """)
##        self.setAttr('path','m'+str(x)+','+str(y))
##        return self
##
##
##    def lineTo(self, x, y):
##        """ Draw a straight line to the given coordinates.
##        """
###        JS("""
###            this['_element']['lineTo'](@{{x}}, @{{y}});
###        """)
##        self.setAttr('path','l'+str(x)+','+str(y))
##        return self
##
##
##    def cplineTo(self, x, y, width=None):
##        """ Draw a curved line to the given coordinates.
##
##            'x' and 'y' define the ending coordinates, and 'width' defines how
##            much of a curve to give to the line.  The line will have horizontal
##            anchors at the start and finish points.
##        """
##        if width != None:
##            JS("""
##               this['_element']['cplineTo'](@{{x}}, @{{y}}, @{{width}});
##            """)
##        else:
##            JS("""
##               this['_element']['cplineTo'](@{{x}}, @{{y}});
##            """)
##        return self
##
##
##    def curveTo(self, x1, y1, x2, y2, x3, y3):
##        """ Draw a bicubic curve to the given coordinates.
##        """
##        JS("""
##            this['_element']['curveTo'](@{{x1}}, @{{y1}}, @{{x}}, @{{y2}}, @{{x3}}, @{{y3}});
##        """)
##        return self
##
##
##    def qcurveTo(self, x1, y1, x2, y2):
##        """ Draw a quadratic curve to the given coordinates.
##        """
##        JS("""
##            this['_element']['qcurveTo'](@{{x1}}, @{{y1}}, @{{x}}, @{{y2}}, @{{x3}}, @{{y3}});
##        """)
##        return self
##
##
##    def addRoundedCorner(self, radius, direction):
##        """ Draw a quarter of a circle from the current drawing point.
##
##            'radius' should be the radius of the circle, and 'direction' should
##            be one of the following strings:
##
##                "lu"   Left up.
##                "ld"   Left down.
##                "ru"   Right up.
##                "rd"   Right down.
##                "ur"   Up right.
##                "ul"   Up left.
##                "dr"   Down right.
##                "dl"   Down left.
##        """
##        JS("""
##            this['_element']['addRoundedCorner'](@{{radius}}, @{{direction}});
##        """)
##        return self
##
##
##    def andClose(self):
##        """ Close the path being drawn.
##        """
##        JS("""
##            this['_element']['andClose']();
##        """)
##        return self



