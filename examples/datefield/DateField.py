# Date Time Example
# Copyright (C) 2009 Yit Choong (http://code.google.com/u/yitchoong/)

import pyjd # dummy in pyjs

from pyjamas.ui.VerticalPanel import  VerticalPanel
from pyjamas.ui.RootPanel import  RootPanel
from pyjamas.ui.TextBox import TextBox
from pyjamas.ui.Button import Button
from pyjamas.ui.Calendar import DateField, Calendar, CalendarPopup
from pyjamas.ui.MonthField import MonthField

from pyjamas import logging
log = logging.getAppendLogger()

class App:
    def onModuleLoad(self):

        text = TextBox()
        df1 = DateField()
        df2 = DateField(format='%Y/%m/%d')
        b = Button("Show Calendar", self)
        self.cal = Calendar()
        df3 = MonthField()

        vp = VerticalPanel()
        vp.setSpacing(10)
        vp.add(df1)
        vp.add(b)
        vp.add(df2)
        vp.add(df3)

        RootPanel().add(vp)

        for obj in [ self.cal, df1, df2, df3 ]:
            obj.addSelectedDateListener(self, dobj=True)
            obj.addSelectedDateListener(getattr(self, "onYMDSelected"))

    def onClick(self, sender):
        p = CalendarPopup(self.cal)
        x = sender.getAbsoluteLeft() + 10
        y = sender.getAbsoluteTop() + 10
        p.setPopupPosition(x,y)
        p.show()

    def onDateSelected(self, d):
        log.info("onDateSelected(%s/%r)" % (d, d))

    def onYMDSelected(self, y, m, d):
        log.info("onYMDSelected(%s,%s,%s)" % (y, m, d))



if __name__ == '__main__':
    pyjd.setup("./public/DateField.html") # dummy in pyjs
    app = App()
    app.onModuleLoad()
    pyjd.run() # dummy in pyjs

