import pyjd # this is dummy in pyjs.
from pyjamas.ui.RootPanel import RootPanel
from pyjamas.Timer import Timer

from __pyjamas__ import doc

from UnitTest import IN_BROWSER, IN_JS

from DockPanelTest import DockPanelTest
from LabelTest import LabelTest
from DOMTest import DOMTest
from EventTest import EventTest

import write
import sys

class RunTests:
    def __init__(self, test_gen):
        self.current_test = None
        self.test_gen = test_gen
        self.testlist = {}
        self.test_idx = 0
        Timer(100, self)

    def add(self, test):
        self.testlist[len(self.testlist)] = test

    def onTimer(self, tid):
        self.start_test()

    def start_test(self):
        print self.test_idx
        if self.test_idx >= len(self.testlist):
            print "num tests outstanding", self.current_test.__class__.__name__, self.current_test.tests_outstanding
            if self.current_test.tests_outstanding > 0:
                Timer(100, self)
                return

            write.display_log_output()
            return

        idx = self.test_idx
        self.test_idx += 1

        test_kls = self.testlist[idx]
        t = test_kls(self.test_gen)
        self.current_test = t
        t.start_next_test = getattr(self, "start_test")
        t.run()

def main(test_gen_out):

    pyjd.setup("public/uitest.html")
    t = RunTests(test_gen_out)
    t.add(DockPanelTest)
    t.add(LabelTest)
    t.add(EventTest)
    t.add(DOMTest)
    pyjd.run()

if __name__ == '__main__':

    # set the test output folder using e.g. hulahop, create
    # the output to be used by tests.

    test_gen_output_folder = None
    if hasattr(sys, 'argv'):
        if len(sys.argv) == 2:
            test_gen_output_folder = sys.argv[1]

    main(test_gen_output_folder )
