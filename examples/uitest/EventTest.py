from pyjamas.ui.RootPanel import RootPanel
from pyjamas.ui.Button import Button

from UnitTest import UnitTest1

from pyjamas import DOM

#TODO see issue 768
class EventTest(UnitTest1):

    def onClick(self, sender):
        self.assertTrue(sender == self.b)
        self.buttonClickTestOccurred = True

    def testButtonClick(self):

        self.buttonClickTestOccurred = False

        self.b = Button("Click Me", self)
        RootPanel('tests').add(self.b)
        self.write_test_output('addButton')

        # simulate button click
        DOM.buttonClick(self.b.getElement())

        if not RootPanel('tests').remove(self.b):
            self.fail("Button added but apparently not owned by RootPanel()")
        self.write_test_output('removeButton')

    def lastTestChecks(self):

        self.assertTrue(self.buttonClickTestOccurred, 'testButtonClick failed')

