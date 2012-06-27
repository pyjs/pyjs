"""Logging handlers for Pyjamas logging based on CPython's logging handlers."""
__author__ = 'Peter Bittner <peter.bittner@gmx.net>'

from cgi import escape
from logging import Handler
from pyjamas import DOM, Window
from __pyjamas__ import doc, JS

class AlertHandler(Handler):
    """A log output handler displaying any log message using an alert popup."""
    def __init__(self):
        Handler.__init__(self)

    def emit(self, record):
        msg = self.format(record)
        Window.alert(msg)

class AppendHandler(Handler):
    """A log output handler showing text in a <div> appended to the end of the
    HTML document. Use the 'div' property to find out the element's ID if you
    want to position or style the output in your Pyjamas application."""
    div = None
    div_id = ''
    output = ''

    def __init__(self, logger_name):
        Handler.__init__(self)
        self.div_id = self.__getSafeNameFor('logging_' + logger_name)

    def __getSafeNameFor(self, name):
        """Strip out all characters that could be invalid for an element ID"""
        from string import ascii_letters, digits
        return ''.join(c for c in name if c in (ascii_letters + digits + '_'))

    def __addLogElement(self):
        """Add a container in the DOM where logging output will be written to.
        This cannot be done in the constructor as it must happen late enough
        to ensure a document body (to add an element to) does already exist."""
        if self.div == None:
            self.div = DOM.createDiv()
            self.div.setAttribute('id', self.div_id)
            DOM.appendChild(doc().body, self.div)

    def emit(self, record):
        msg = self.format(record)
        msg = escape(msg)
        msg = msg.replace("\n", "<br/>\n") + "<br/>\n"
        self.output += msg
        self.__addLogElement()
        DOM.setInnerHTML(self.div, self.output)

class ConsoleHandler(Handler):
    """A log output handler making use of Firebug's console.log() function."""

    __consoleFuncForLevel = None

    def __init__(self):
        Handler.__init__(self)
        self.__consoleFuncForLevel = {
            'DEBUG':    self.__debug,
            'INFO':     self.__info,
            'WARNING':  self.__warn,
            'ERROR':    self.__error,
            'CRITICAL': self.__error
        }

    def emit(self, record):
        """Print a message using the console.debug/info/warn/error/log()
        functions. Use a simple print() as a fallback in browsers that don't
        support console.log -- including Pyjamas Desktop."""
        msg = self.format(record)
        func = self.__consoleFuncForLevel.get(record.levelname, self.__log)
        try:
            # NOTE: must be that clumsy, because JS() allows constants only!!
            func(msg)
        except:
            print(msg)

    def __debug(self, msg):
        JS(" console['debug'](@{{msg}}); ")

    def __info(self, msg):
        JS(" console['info'](@{{msg}}); ")

    def __warn(self, msg):
        JS(" console['warn'](@{{msg}}); ")

    def __error(self, msg):
        JS(" console['error'](@{{msg}}); ")

    def __log(self, msg):
        JS(" console['log'](@{{msg}}); ")

class NullHandler(Handler):
    """A log output handler that does nothing. Use to disable logging."""
    def __init__(self):
        Handler.__init__(self)

    def emit(self, record):
        pass

