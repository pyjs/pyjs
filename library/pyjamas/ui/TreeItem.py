# Copyright 2006 James Tauber and contributors
# Copyright (C) 2009 Luke Kenneth Casson Leighton <lkcl@lkcl.net>
# Copyright (C) 2011-2012 Vsevolod Fedorov <vsevolod.fedorov@gmail.com>
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
from pyjamas import DOM
from pyjamas import Factory
from pyjamas.Canvas.GWTCanvas import GWTCanvas
from pyjamas.Canvas import Color

from pyjamas.ui.UIObject import UIObject
from pyjamas.ui.TreeContentPanel import TreeContentPanel

# http://www.greywyvern.com/code/php/binary2base64 - yaay!
# http://websemantics.co.uk/online_tools/image_to_data_uri_convertor/
# this 2nd one didn't put %3D at the end, you have to back-convert that
# into "==" characters.
tree_closed = "data:image/gif;base64,R0lGODlhEAAQAJECAMzMzAAAAP///wAAACH5BAEAAAIALAAAAAAQABAAAAIjlI+py+1vgJxzAYtNOFd1sUVYQJLCh3zhmYFcm1oUBdU2VAAAOw=="
tree_open = "data:image/gif;base64,R0lGODlhEAAQAJECAAAAAMDAwAAAAP///yH5BAEAAAIALAAAAAAQABAAAAIflI+py+1vgpxzBYvV1TldAILC5nUIeZoHulIUBMdQAQA7"
tree_white = "data:image/gif;base64,R0lGODlhEAAQAJEAAP///wAAAP///wAAACH5BAEAAAIALAAAAAAQABAAAAIOlI+py+0Po5y02ouzPgUAOw=="

class TreeItem(UIObject):

    # also callable as TreeItem(widget)
    def __init__(self, html=None, **ka):
        self.children = []
        self.attached = False
        self.contentPanel = None
        self.itemTable = None
        self.contentElem = None
        self.imgElem = None
        self.childSpanElem = None
        self.open = False
        self.parent = None
        self.selected = False
        self.tree = None
        self.userObject = None

        element = ka.pop('Element', None) or DOM.createDiv()
        self.setElement(element)

        self.itemTable = DOM.createTable()
        self.contentElem = DOM.createSpan()
        self.childSpanElem = DOM.createSpan()
        self.imgElem = self.createImage()

        tbody = DOM.createTBody()
        tr = DOM.createTR()
        tdImg = DOM.createTD()
        tdContent = DOM.createTD()
        DOM.appendChild(self.itemTable, tbody)
        DOM.appendChild(tbody, tr)
        DOM.appendChild(tr, tdImg)
        DOM.appendChild(tr, tdContent)
        DOM.setStyleAttribute(tdImg, "verticalAlign", "middle")
        DOM.setStyleAttribute(tdContent, "verticalAlign", "middle")
        DOM.setStyleAttribute(self.getElement(), "cursor", "pointer")

        DOM.appendChild(self.getElement(), self.itemTable)
        DOM.appendChild(self.getElement(), self.childSpanElem)
        DOM.appendChild(tdImg, self.imgElem)
        DOM.appendChild(tdContent, self.contentElem)

        self.setStyleName(tdImg, "gwt-TreeItemTdImg", True)
        self.setStyleName(tdContent, "gwt-TreeItemTdContent", True)

        # XXX - can't set pos relative on a div node,
        # or white_space on an HTML Table..
        try:
            DOM.setAttribute(self.getElement(), "position", "relative")
        except:
            pass
        DOM.setStyleAttribute(self.contentElem, "display", "inline")
        DOM.setStyleAttribute(self.getElement(), "whiteSpace", "nowrap")
        try:
            DOM.setAttribute(self.itemTable, "whiteSpace", "nowrap")
        except:
            pass
        DOM.setStyleAttribute(self.childSpanElem, "whiteSpace", "nowrap")
        self.setStyleName(self.contentElem, "gwt-TreeItem", True)

        #if not ka.has_key('StyleName'): ka['StyleName']="gwt-TreeItem"

        if html is not None:
            try:
                # messy. pyjd can do unicode, pyjs can't
                if isinstance(html, unicode):
                    ka['HTML'] = html
                elif isinstance(html, basestring):
                    ka['HTML'] = html
                else:
                    ka['Widget'] = html
            except:
                if isinstance(html, basestring):
                    ka['HTML'] = html
                else:
                    ka['Widget'] = html

        UIObject.__init__(self, **ka)

    def __iter__(self):
        return self.children.__iter__()

    def createImage(self):
        return DOM.createImg()

    # also callable as addItem(widget) and addItem(itemText)
    def addItem(self, item):
        return self.insertItem(item)

    # also callable as addItem(widget) and addItem(itemText)
    def insertItem(self, item, index=None):
        if not hasattr(item, "getTree"):
            #if not item.getTree:
            item = TreeItem(item)

        if (item.getParentItem() is not None) or (item.getTree() is not None):
            item.remove()

        item.setTree(self.tree)
        item.setParentItem(self)
        if index is None:
            self.children.append(item)
        else:
            self.children.insert(index, item)
        DOM.setStyleAttribute(item.getElement(), "marginLeft", "16px")
        if index is None:
            DOM.appendChild(self.childSpanElem, item.getElement())
        else:
            DOM.insertChild(self.childSpanElem, item.getElement(), index)

        if len(self.children) == 1:
            self.updateState()

        return item

    def onAttach(self):
        if self.attached:
            return
        self.attached = True
        for item in self.children:
            item.onAttach()
        w = self.getWidget()
        if w:
           w.onAttach()

    def onDetach(self):
        self.attached = False
        for item in self.children:
            item.onDetach()
        w = self.getWidget()
        if w:
           w.onDetach()

    def getChild(self, index):
        if (index < 0) or (index >= len(self.children)):
            return None

        return self.children[index]

    def getChildCount(self):
        return len(self.children)

    def getChildIndex(self, child):
        return self.children.index(child)

    def getHTML(self):
        return DOM.getInnerHTML(self.contentElem)

    def getText(self):
        return DOM.getInnerText(self.contentElem)

    def getParentItem(self):
        return self.parent

    def getState(self):
        return self.open

    def getTree(self):
        return self.tree

    def getUserObject(self):
        return self.userObject

    def getWidget(self):
        if self.contentPanel is None:
            return None

        return self.contentPanel.getWidget()

    def isSelected(self):
        return self.selected

    def remove(self):
        if self.parent is not None:
            self.parent.removeItem(self)
        elif self.tree is not None:
            self.tree.removeItem(self)

    def removeItem(self, item):
        if item not in self.children:
            return

        item.setTree(None)
        item.setParentItem(None)
        self.children.remove(item)
        DOM.removeChild(self.childSpanElem, item.getElement())
        if len(self.children) == 0:
            self.updateState()

    def removeItems(self):
        while self.getChildCount() > 0:
            self.removeItem(self.getChild(0))

    def setHTML(self, html):
        self.clearContentPanel()
        DOM.setInnerHTML(self.contentElem, html)

    def setText(self, text):
        self.clearContentPanel()
        DOM.setInnerText(self.contentElem, text)

    def setSelected(self, selected):
        if self.selected == selected:
            return
        self.selected = selected
        self.setStyleName(self.contentElem, "gwt-TreeItem-selected", selected)

    def setState(self, open, fireEvents=True):

        # lkcl: experiment with allowing event state changed to be
        # fired even on items with no children.  otherwise you never
        # get to find out if an end-item was selected!
        if not open or len(self.children) != 0:
            self.open = open
            self.updateState()

        if fireEvents:
            self.tree.fireStateChanged(self)

    def setUserObject(self, userObj):
        self.userObject = userObj

    def setWidget(self, widget):
        self.ensureContentPanel()
        self.contentPanel.setWidget(widget)

    def clearContentPanel(self):
        if self.contentPanel is not None:
            child = self.contentPanel.getWidget()
            if child is not None:
                self.contentPanel.remove(child)

            if self.tree is not None:
                self.tree.disown(self.contentPanel)
                self.contentPanel = None

    def ensureContentPanel(self):
        if self.contentPanel is None:
            DOM.setInnerHTML(self.contentElem, "")
            self.contentPanel = TreeContentPanel(self.contentElem)
            self.contentPanel.setTreeItem(self)
            if self.getTree() is not None:
                self.tree.adopt(self.contentPanel)

    def addTreeItems(self, accum):
        for item in self.children:
            accum.append(item)
            item.addTreeItems(accum)

    def getChildren(self):
        return self.children

    def getContentElem(self):
        return self.contentElem

    def getContentHeight(self):
        return DOM.getIntAttribute(self.itemTable, "offsetHeight")

    def getImageElement(self):
        return self.imgElem

    def getTreeTop(self):
        item = self
        ret = 0

        while item is not None:
            ret += DOM.getIntAttribute(item.getElement(), "offsetTop")
            item = item.getParentItem()

        return ret

    def getFocusableWidget(self):
        widget = self.getWidget()
        if hasattr(widget, "setFocus"):
            return widget
        return None

    def imgSrc(self, img):
        if self.tree is None:
            return img
        src = self.tree.getImageBase() + img
        return src

    def setParentItem(self, parent):
        self.parent = parent

    def setTree(self, tree):
        if self.tree == tree:
            return

        if self.tree is not None:
            if self.tree.getSelectedItem() == self:
                self.tree.setSelectedItem(None)

            if self.contentPanel is not None:
                self.tree.disown(self.contentPanel)

        self.tree = tree
        for child in self.children:
            child.setTree(tree)
        self.updateState()
        if tree is not None and self.contentPanel is not None:
                tree.adopt(self.contentPanel)

    def updateState(self):
        if len(self.children) == 0:
            self.setVisible(self.childSpanElem, False)
            #DOM.setAttribute(self.imgElem, "src", self.imgSrc("tree_white.gif"))
            self.drawImage("white")
            return

        if self.open:
            self.setVisible(self.childSpanElem, True)
            self.drawImage("open")
        else:
            self.setVisible(self.childSpanElem, False)
            self.drawImage("closed")

    def updateStateRecursive(self):
        self.updateState()
        for i in range(len(self.children)):
            child = self.children[i]
            child.updateStateRecursive()

    def drawImage(self, mode):
        if mode == "white":
            src = tree_white
        elif mode == "open":
            src = tree_open
        elif mode == "closed":
            src = tree_closed

        DOM.setAttribute(self.imgElem, "src", src)


class RootTreeItem(TreeItem):
    def addItem(self, item):
        self.insertItem(item)

    def insertItem(self, item, index=None):
        if (item.getParentItem() is not None) or (item.getTree() is not None):
            item.remove()
        item.setTree(self.getTree())

        item.setParentItem(None)
        if index is None:
            self.children.append(item)
        else:
            self.children.insert(index, item)

        DOM.setIntStyleAttribute(item.getElement(), "marginLeft", 0)

    def removeItem(self, item):
        if item not in self.children:
            return

        item.setTree(None)
        item.setParentItem(None)
        self.children.remove(item)

Factory.registerClass('pyjamas.ui.TreeItem', 'TreeItem', TreeItem)

