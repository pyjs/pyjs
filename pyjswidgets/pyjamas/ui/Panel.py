# Copyright 2006 James Tauber and contributors
# Copyright (C) 2009 Luke Kenneth Casson Leighton <lkcl@lkcl.net>
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
from pyjamas import Factory
from pyjamas import DOM

from pyjamas.ui.Widget import Widget

class PanelBase(object):

    def clear(self):
        """ use this method, due to list changing as it's being iterated.
            also, it's possible to use this method even
        """
        children = []
        for child in self.__iter__():
            children.append(child)

        for child in children:
            self.remove(child)

    def doAttachChildren(self):
        for child in self:
            child.onAttach()

    def doDetachChildren(self):
        for child in self:
            child.onDetach()

    def getWidgetCount(self):
        return len(self.getChildren())

    def getWidget(self, index):
        return self.getChildren()[index]

    def getIndexedChild(self, index):
        return self.getWidget(index)

    def addIndexedItem(self, index, child):
        self.add(child)

    def getWidgetIndex(self, child):
        return self.getChildren().index(child)

    def getChildren(self):
        return self.children # assumes self.children: override if needed.

    def setWidget(self, index, widget):
        """ Insert (or optionally replace) the widget at the given index
            with a new one
        """
        existing = self.getWidget(index)
        if existing is not None:
            self.remove(existing)
        self.insert(widget, index)

    def append(self, widget):
        return self.add(widget)

    def __setitem__(self, index, widget):
        return self.setWidget(index, widget)

    def __getitem__(self, index):
        return self.getWidget(index)

    def __len__(self):
        return len(self.getChildren())

    def __nonzero__(self):
        return self is not None

    def __iter__(self):
        return self.getChildren().__iter__()


class Panel(PanelBase, Widget):
    def __init__(self, **kwargs):
        self.children = []
        PanelBase.__init__(self)
        Widget.__init__(self, **kwargs)

    def disown(self, widget):
        if widget.getParent() is not self:
            raise Exception("widget %s is not a child of this panel %s" % \
                             (str(widget), str(self)))
        element = widget.getElement()
        widget.setParent(None)
        parentElement = DOM.getParent(element)
        if parentElement is not None:
            DOM.removeChild(parentElement, element)

    def adopt(self, widget, container):
        if container is not None:
            widget.removeFromParent()
            if indexBefore:
                DOM.insertChild(container, widget.getElement(), indexBefore)
            else:
                DOM.appendChild(container, widget.getElement())
        widget.setParent(self)


Factory.registerClass('pyjamas.ui.Panel', 'Panel', Panel)

