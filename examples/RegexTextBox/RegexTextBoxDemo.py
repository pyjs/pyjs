import pyjd  # dummy in pyjs

from pyjamas import Window, DOM
from pyjamas.ui.FlexTable import FlexTable
from pyjamas.ui.RootPanel import RootPanel
from pyjamas.ui.VerticalPanel import VerticalPanel
from pyjamas.ui.HTML import HTML
from RegexTextBox import RegexTextBox

def display_ok(obj):
    obj.setStyleName("gwt-textbox-ok")

def display_error(obj):
    obj.setStyleName("gwt-textbox-error")

class RegexTextBoxDemo:
    def onModuleLoad(self):

        _example_descr=HTML("""This example shows how to validate text using
 a TextBox.  A new class called RegexTextBox, which inherits from TextBox
 validates text, when focus is removed (ie, onblur event).<br>
In the table below, TextBoxes in the 'Valid Text' column contain text 
strings that match that rows regular expression.  TextBoxes in the 'Invalid Text'
column contain strings that violates the same regular expressions.  Feel free
to modify the text to test different values to see if they are valid or not.
<p>""")

        self._table=FlexTable(BorderWidth=0)
        self._table.setStyleName("gwt-table")
        self._setHeaders()

        self._row=1
        for _descr, _regex, _correct, _wrong in self._get_data():
            self._rowHelper(_descr, _regex, _correct, _wrong)
            self._row+=1

        _panel=VerticalPanel()
        _panel.add(_example_descr)
        _panel.add(self._table)
        RootPanel().add(_panel)

    def _setHeaders(self):
        self._table.setHTML(0,0, "<b>Description</b>")
        self._table.setHTML(0,1, "<b>Regex</b>")
        self._table.setHTML(0,2, "<b>Valid Text</b>")
        self._table.setHTML(0,3, "<b>Invalid Text</b>")

    def _rowHelper(self, text, regex, value1, value2):
        self._table.setHTML(self._row, 0, text)
        self._table.setHTML(self._row, 1, regex)

        _rtb=RegexTextBox()
        _rtb.setRegex(regex)
        _rtb.setText(value1)
        _rtb.appendValidListener(display_ok)
        _rtb.appendInvalidListener(display_error)
        _rtb.validate(None)
        self._table.setWidget(self._row, 2, _rtb)

        _rtb1=RegexTextBox()
        _rtb1.setRegex(regex)
        _rtb1.setText(value2)
        _rtb1.appendValidListener(display_ok)
        _rtb1.appendInvalidListener(display_error)
        _rtb1.validate(None)
        self._table.setWidget(self._row, 3, _rtb1)

    def _get_data(self):
        return [['Positive Unsigned Integer', r'^\d+$', '123', '1a2'],
                ['Signed Integer', r'^[+-]?\d+$', '+321', '321-'],
                ['No whitespace', r'^\S+$', 'pyjamas', '1 3'],
                ['Date in (MM/DD/YYYY) format', r'^\d\d/\d\d/\d{4}$', 
                   '12/21/2012', '12-21-2012'],
                ['Non digits', r'^\D+$', 'pyjamas', '1 3'],
               ]  


if __name__ == '__main__':
    pyjd.setup("./public/RegexTextBoxDemo.html")
    app = RegexTextBoxDemo()
    app.onModuleLoad()
    pyjd.run()
