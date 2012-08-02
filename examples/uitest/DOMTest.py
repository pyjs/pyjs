from pyjamas.ui.RootPanel import RootPanel
from pyjamas import DOM

from UnitTest import UnitTest1

from __pyjamas__ import doc

#TODO: see issue 768
class DOMTest(UnitTest1):

    def testDivHTML(self):
        e = DOM.getElementById('tests')
        div = DOM.createElement('div')
        DOM.appendChild(e, div)
        DOM.setInnerHTML(div, 'hello world\n')
        self.write_test_output('addDiv')

        DOM.removeChild(e, div)
        self.write_test_output('removeDiv')

    def testDivText(self):
        e = DOM.getElementById('tests')
        div = DOM.createElement('div')
        DOM.appendChild(e, div)
        div2 = DOM.createElement('div')
        DOM.appendChild(div, div2)
        DOM.setInnerText(div2, 'hello world\n')
        self.write_test_output('addDiv')

        DOM.removeChild(e, div)
        self.write_test_output('removeDiv')

