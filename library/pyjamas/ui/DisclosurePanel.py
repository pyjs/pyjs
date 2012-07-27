# Copyright 2006 James Tauber and contributors
# Copyright (C) 2009 Luke Kenneth Casson Leighton <lkcl@lkcl.net>
# Copyright (C) 2010 Glenn Washburn <crass@berlios.de>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from pyjamas.ui.Composite import Composite
from pyjamas import Factory
from pyjamas.ui.Widget import Widget
from pyjamas.ui.SimplePanel import SimplePanel
from pyjamas.ui.VerticalPanel import VerticalPanel
from pyjamas.ui import Event
from pyjamas import DOM
import pygwt

class ClickableHeader(SimplePanel):
    def __init__(self, disclosurePanel, **kwargs):
        element = kwargs.pop('Element', DOM.createAnchor())
        SimplePanel.__init__(self, element)
        self.disclosurePanel = disclosurePanel
        element = self.getElement()
        DOM.setAttribute(element, "href", "javascript:void(0);");
        DOM.setStyleAttribute(element, "display", "block")
        self.sinkEvents(Event.ONCLICK)
        self.setStyleName("header")

    def onBrowserEvent(self, event):
        etype = DOM.eventGetType(event)
        if etype == "click":
            DOM.eventPreventDefault(event)
            newstate = not self.disclosurePanel.getOpen()
            self.disclosurePanel.setOpen(newstate)

Factory.registerClass('pyjamas.ui.DisclosurePanel', 'ClickableHeader', ClickableHeader)

class DefaultHeader(Widget):
    def __init__(self, text, images=True):
        Widget.__init__(self)
        self.setImageBase(images)

        self.root = DOM.createTable()
        self.tbody = DOM.createTBody()
        self.tr = DOM.createTR()
        self.imageTD = DOM.createTD()
        self.labelTD = DOM.createTD()
        self.imgElem = DOM.createImg()

        self.setElement(self.root)
        DOM.appendChild(self.root, self.tbody)
        DOM.appendChild(self.tbody, self.tr)
        DOM.appendChild(self.tr, self.imageTD)
        DOM.appendChild(self.tr, self.labelTD)
        DOM.appendChild(self.imageTD, self.imgElem)

        self.setText(text)

    def getText(self):
        return DOM.getInnerText(self.labelTD)

    def setText(self, text):
        DOM.setInnerText(self.labelTD, text)

    def onOpen(self, panel):
        self.updateState(True)

    def onClose(self, panel):
        self.updateState(False)

    def setImageBase(self, images):
        self.imageBase = pygwt.getImageBaseURL(images)

    def updateState(self, setOpen):
        if setOpen:
            DOM.setAttribute(self.imgElem, "src",
                             self.imageBase + "disclosurePanelOpen.png")
        else:
            DOM.setAttribute(self.imgElem, "src",
                             self.imageBase + "disclosurePanelClosed.png")


# TODO: must be able to pass in DisclosurePanel argument by a means
# *other* than an actual class instance.
#Factory.registerClass('pyjamas.ui.DisclosurePanel', 'DefaultHeader', DefaultHeader)

class DisclosurePanel(Composite):

    def __init__(self, *args, **kwargs):

        self.handlers = []
        self.content = None
        self.images = False

        # this is awkward: VerticalPanel is the composite,
        # so we get the element here, and pass it in to VerticalPanel.
        element = kwargs.pop('Element', None)

        # process the passed arguments
        headerText = headerWidget = None
        isOpen = False
        if len(args) == 1:
            header = args[0]
        if len(args) == 2:
            header, isOpen = args[:2]
        # apparently "basestring" is not understood
        if isinstance(header, basestring):
            headerText = header
        else:
            headerWidget = header
        isOpen = kwargs.pop('isOpen', isOpen)
        headerText = kwargs.pop('header', headerText)
        headerWidget = kwargs.pop('header', headerWidget)
        # TODO: add ImageBundle
        # images = kwargs.pop('images', None)

        # If both headerText and headerWidget are arguments, headerText will
        # be used to preserve API compatibility.
        headerContent = headerWidget
        if headerText is not None or headerContent is None:
            if headerText is None:
                headerText = ""
            headerContent = DefaultHeader(headerText)

        self.mainPanel = VerticalPanel(Element=element)

        self._init_header(headerContent)

        self.contentWrapper = SimplePanel()
        self.mainPanel.add(self.header)
        self.mainPanel.add(self.contentWrapper)
        DOM.setStyleAttribute(self.contentWrapper.getElement(),
                              "padding", "0px");
        DOM.setStyleAttribute(self.contentWrapper.getElement(),
                              "overflow", "hidden");

        kwargs['StyleName'] = kwargs.get('StyleName', "gwt-DisclosurePanel")
        Composite.__init__(self, self.mainPanel, **kwargs)

        # Must call setOpen after creating the initializing the object
        self.isOpen = None
        self.setOpen(isOpen)

        self.setContentDisplay()

    def _init_header(self, headerContent):
        self.header = ClickableHeader(self)
        self.headerObj = headerContent
        self.addEventHandler(self.headerObj)
        self.setHeader(self.headerObj)

    def add(self, widget):
        if self.getContent() is None:
            self.setContent(widget)

    def addEventHandler(self, handler):
        self.handlers.append(handler)

    def removeEventHandler(self, handler):
        self.handlers.remove(handler)

    def clear(self):
        self.setContent(None)

    def getContent(self):
        return self.content

    def getHeader(self):
        return self.header.getWidget()

    def getOpen(self):
        return self.isOpen

    def getImages(self):
        return self.images

    def remove(self, widget):
        if widget == self.getContent():
            self.setContent(None)
            return True
        return False

    def setContent(self, widget):
        if self.content is not None:
            self.contentWrapper.setWidget(None)
            self.content.removeStyleName("content")

        self.content = widget
        if self.content is not None:
            self.contentWrapper.setWidget(self.content)
            self.content.addStyleName("content")
            self.setContentDisplay()

    def setHeader(self, widget):
        self.header.setWidget(widget)

    def setOpen(self, isOpen):
        if self.isOpen == isOpen:
            return
        self.isOpen = isOpen
        self.setContentDisplay()
        self.fireEvent()

    def setImages(self, images):
        if self.images == images:
            return
        self.images = images
        header = self.getHeader()
        if header is not None and isinstance(header,DefaultHeader):
            header.setImageBase(images)
            header.updateState(self.getOpen())

    def fireEvent(self):
        for handler in self.handlers:
            if self.isOpen:
                handler.onOpen(self)
            else:
                handler.onClose(self)

    def setContentDisplay(self):
        if self.isOpen:
            self.addStyleName("open")
            self.removeStyleName("closed")
        else:
            self.addStyleName("closed")
            self.removeStyleName("open")
        self.contentWrapper.setVisible(self.isOpen)

Factory.registerClass('pyjamas.ui.DisclosurePanel', 'DisclosurePanel', DisclosurePanel)

