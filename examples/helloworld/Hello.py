import pyjd # this is dummy in pyjs.
from pyjamas.ui.RootPanel import RootPanel
from pyjamas.ui.Button import Button
from pyjamas.ui.HTML import HTML
from pyjamas.ui.Label import Label
from pyjamas import Window

import pygwt

def greet(fred):
    fred.setText("No, really click me!")
    Window.alert("Hello, AJAX!")

if __name__ == '__main__':
    pyjd.setup("public/Hello.html?fred=foo#me")
    b = Button("Click me", greet, StyleName='teststyle')
    h = HTML("<b>Hello World</b> (html)", StyleName='teststyle')
    l = Label("Hello World (label)", StyleName='teststyle')
    base = HTML("Hello from %s" % pygwt.getModuleBaseURL(),
                                  StyleName='teststyle')
    RootPanel().add(b)
    RootPanel().add(h)
    RootPanel().add(l)
    RootPanel().add(base)
    pyjd.run()
