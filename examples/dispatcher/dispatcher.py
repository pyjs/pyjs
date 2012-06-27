import pyjd # this is dummy in pyjs.
from pyjamas import Window
from pyjamas import dispatcher

import pygwt

from __javascript__ import document, window

def greet():
    Window.alert("hello world from pythopn function: greet()")

class CL(object):
    def method(self):
        Window.alert("hello world from object's method")

if __name__=='__main__':
    pyjd.setup("public/Hello.html")

    d=dispatcher.PyjsDispatcher()
    d.greet=greet
    d.obj=CL()
    d.install()

    pyjd.run()
