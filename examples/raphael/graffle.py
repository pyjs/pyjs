
import pyjd
from pyjamas.ui.RootPanel   import RootPanel
from pyjamas.ui.TabPanel import TabPanel
from pyjamas.ui.SimplePanel import SimplePanel
from pyjamas.ui.HorizontalPanel import HorizontalPanel
from pyjamas.ui.Label import Label
from pyjamas.ui.HTML import HTML
from pyjamas.ui import HasAlignment
from pyjamas.raphael.raphael import Raphael,DOCK_CONNECTION
from pyjamas import DOM


class Graffle(SimplePanel):
    def __init__(self,width=600,height=300):
        SimplePanel.__init__(self)
        self.canvas = Raphael(width,height)
        self.add(self.canvas)
    def draw(self):
        self.circle1=self.canvas.circle(50,50,25)
        self.circle1.setAttr('fill','#000')
        self.circle1.setAttrs({'cursor':'move','opacity':0.6})
        self.circle1.drag(self._move_circle,start,up)

        self.circle2=self.canvas.circle(150,100,25)
        self.circle2.setAttr('fill','#000')
        self.circle2.setAttrs({'cursor':'move','opacity':0.6})
        self.circle2.drag(self._move_circle,start,up)

        self.rect1=self.canvas.rect(200,100,30,30)
        self.rect1.setAttr('fill','#000')
        self.rect1.drag(self._move_rect,start,up)

        self.rect2=self.canvas.rect(200,150,30,30)
        self.rect2.setAttr('fill','#000')
        self.rect2.drag(self._move_rect,start,up)

    def connect(self):
        line={'stroke':'#fff','stroke-width':3}
        bg={'stroke': '#000', 'stroke-width':5}
        self.connection_rect=self.canvas.connection(self.rect1,self.rect2,line=line,bg=bg)

        line={'stroke':'#fff','stroke-width':3}
        bg={'stroke': '#000', 'stroke-width':5}
        self.connection_circle=self.canvas.connection(self.circle1,self.circle2,line=line,bg=bg,cp1=DOCK_CONNECTION.EAST,cp2=DOCK_CONNECTION.WEST)

    def _move_rect(self,obj,dx,dy,x,y):
        obj.translate(dx-obj.dx,dy-obj.dy)
        obj.dx=dx
        obj.dy=dy
        self.connection_rect.draw()

    def _move_circle(self,obj,dx,dy,x,y):
        obj.translate(dx-obj.dx,dy-obj.dy)
        obj.dx=dx
        obj.dy=dy
        self.connection_circle.draw()


def start(obj,x,y):
    obj.dx=0
    obj.dy=0

def up(obj, event):
    pass

if __name__ == "__main__":
    pyjd.setup("public/graffle.html")
    graffle=Graffle()
    RootPanel().add(graffle)
    graffle.draw()
    graffle.connect()
    pyjd.run()
