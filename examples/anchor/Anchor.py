import pyjd
from pyjamas.ui.RootPanel import RootPanel
from pyjamas.ui.Image import Image
from pyjamas.ui.Anchor import Anchor

if __name__ == '__main__':
    pyjd.setup("public/Anchor.html")

    root = RootPanel()
    image = Image('http://pyjs.org/assets/images/pyjs.128x128.png')
    anchor = Anchor(Widget=image, Href='http://pyjs.org', Title='Pyjs website')
    root.add(anchor)

    pyjd.run()

