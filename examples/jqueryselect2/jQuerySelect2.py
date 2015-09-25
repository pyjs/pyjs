import pyjd # this is dummy in pyjs

from pyjamas.ui.VerticalPanel import VerticalPanel
from pyjamas.ui.RootPanel import RootPanel
from pyjamas.ui.Button import Button
from pyjamas.ui.DialogBox import DialogBox
from pyjamas import logging
from pyjamas import Window

from Select2TaggingComponent import Select2TaggingComponent

log = logging.getConsoleLogger()

class MyTagger(VerticalPanel):

    def __init__ (self, tags = None, width = 300, selected = None, myid = None):
        VerticalPanel.__init__(self)
        self.s2 = Select2TaggingComponent(tags, width, selected, myid)
        self.reset_button = Button("Reset", self)
        self.show_values_button = Button("Show", self)
        self.add(self.s2)
        self.add(self.reset_button)
        self.add(self.show_values_button)
        self.s2.change = self.change

    def change(self):
        txt = "Object with id=%s has value '%s'" % (self.s2.myid, self.s2.get_val())
        log.info(txt)
        self.create_popup(txt)

    def create_popup(self, txt):
        popup = DialogBox(False, False)
        popup.onClick = lambda w: popup.hide()
        popup.setHTML('<b>%s</b>' % (txt))
        popup.setWidget(Button('Close', popup))
        popup.show()

    def onClick(self, sender):
        if sender == self.reset_button:
            log.info('Updating')
            values = [ { 'id' : 'id1', 'text': 'text1'}, { 'id' : 'id2', 'text': 'text2'}]
            self.s2.update(values)
        elif sender == self.show_values_button:
            txt = "Object with id=%s has value '%s'" % (self.s2.myid, self.s2.get_val())
            log.info(txt)
            self.create_popup(txt)

class MainWindow:

    def onModuleLoad(self):

        # TODO: the change event does not work properly when there are
        #   several Select2TaggingComponent.
        tagger1 = MyTagger(myid = 'example1')
        tagger2 = MyTagger(myid = 'example2')

        # Get rid of scrollbars, and clear out the window's built-in margin,
        # because we want to take advantage of the entire client area.
        Window.enableScrolling(False)
        Window.setMargin("0px")

        # Add the component to the DOM
        RootPanel().add(tagger1)
        RootPanel().add(tagger2)

        # Now that it is in the DOM, select2 can perform the final setup
        # TODO: is it possible that the component automatically detects this?
        tagger1.s2.final_setup()
        tagger2.s2.final_setup()

if __name__ == '__main__':
    pyjd.setup("./public/jQuerySelect2.html")
    w = MainWindow()
    w.onModuleLoad()
    pyjd.run()
