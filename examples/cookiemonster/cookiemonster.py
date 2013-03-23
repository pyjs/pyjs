from pyjamas.ui.RootPanel import RootPanel
from pyjamas.ui.TextArea import TextArea
from pyjamas.ui.Label import Label
from pyjamas.ui.HTML import HTML
from pyjamas.ui.Button import Button
from pyjamas.ui.VerticalPanel import VerticalPanel
from pyjamas.ui.HorizontalPanel import HorizontalPanel
from pyjamas.Cookies import setCookie, getCookie


class CookieExample:
    COOKIE_NAME = "myCookie"
    def onModuleLoad(self):
        try:
            setCookie(COOKIE_NAME, "setme", 100000)
        except:
            pass

        self.status=Label()
        self.text_area = TextArea()
        self.text_area.setText(r"Me eat cookie!")
        self.text_area.setCharacterWidth(80)
        self.text_area.setVisibleLines(8)
        self.button_py_set = Button("Set Cookie", self)
        self.button_py_read = Button("Read Cookie ", self)

        buttons = HorizontalPanel()
        buttons.add(self.button_py_set)
        buttons.add(self.button_py_read)
        buttons.setSpacing(8)
        info = r'This demonstrates setting and reading information using cookies.'
        panel = VerticalPanel()
        panel.add(HTML(info))
        panel.add(self.text_area)
        panel.add(buttons)
        panel.add(self.status)

        RootPanel().add(panel)


    def onClick(self, sender):
        """
        Run when any button is clicked
        """
        if sender.getText() == "Set Cookie":
            #clicked the set cookie button
            text = self.text_area.getText()
            #print goes to console.log
            print "setting cookie to:", text
            #Note: this sets the cookie on the top level
            setCookie(COOKIE_NAME, text, 10000, path='/')
        else:
            cookie_text = getCookie(COOKIE_NAME)
            if cookie_text is None:
                print "No Cookie"
            else:
                print "myCookie", cookie_text
                self.status.setText(cookie_text)


if __name__ == '__main__':
    app = CookieExample()
    app.onModuleLoad()

