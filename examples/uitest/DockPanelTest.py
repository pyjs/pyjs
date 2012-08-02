from pyjamas.ui.RootPanel import RootPanel
from pyjamas.ui.DockPanel import DockPanel
from pyjamas.ui.Label import Label

from UnitTest import UnitTest1

from __pyjamas__ import doc

#TODO: see issue #768
class DockPanelTest(UnitTest1):

    def testDockAdd(self):
        self.d = DockPanel()
        RootPanel('tests').add(self.d)
        self.write_test_output('adddockpanel')

        if not RootPanel('tests').remove(self.d):
            self.fail("DockPanel added but apparently not owned by RootPanel()")
        self.write_test_output('removedockpanel')

    def testDockAddCentre(self):
        self.d = DockPanel()
        RootPanel('tests').add(self.d)
        l = Label("Hello World (label)", StyleName='teststyle')
        self.d.add(l, DockPanel.CENTER)
        self.write_test_output('addcentrelabel')

        self.d.remove(l)
        self.write_test_output('removecentrelabel')

        l2 = Label("Hello World 2 (label)", StyleName='teststyle')

        self.d.add(l2, DockPanel.CENTER)
        self.write_test_output('addcentrelabel2')

        if not RootPanel('tests').remove(self.d):
            self.fail("DockPanel added but apparently not owned by RootPanel()")
        self.write_test_output('removedock')

