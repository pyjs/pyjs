# Copyright 2006 James Tauber and contributors
# Copyright (C) 2009, 2010 Luke Kenneth Casson Leighton <lkcl@lkcl.net>
# Copyright (C) 2012 Alok Parlikar <aup@cs.cmu.edu>
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

from pyjamas.ui.PopupPanel import PopupPanel
from pyjamas.ui.HTML import HTML
from pyjamas.ui.FlexTable import FlexTable
from pyjamas.ui.SimplePanel import SimplePanel
from pyjamas.ui import HasHorizontalAlignment
from pyjamas.ui import HasVerticalAlignment
from pyjamas.ui import GlassWidget


class DialogBox(PopupPanel):
    _props = [
        ("caption", "Caption", "HTML", None),
    ]

    def __init__(self, autoHide=None, modal=True, centered=False,
                 **kwargs):
        # Init section
        self.dragging = False
        self.dragStartX = 0
        self.dragStartY = 0
        self.child = None
        self.panel = FlexTable(
            Height="100%",
            BorderWidth="0",
            CellPadding="0",
            CellSpacing="0",
        )

        cf = self.panel.getCellFormatter()
        rf = self.panel.getRowFormatter()

        # Arguments section
        self.modal = modal
        self.caption = HTML()
        self.caption.setStyleName("Caption")
        self.caption.addMouseListener(self)

        try:
            self.generate_gwt15 = kwargs['gwt15']
            # Make the DialogBox a 3x3 table, like GWT does, with
            # empty elements with specific style names. These can be
            # used with CSS to, for example, create border around the
            # dialog box.
        except:
            self.generate_gwt15 = False

        if not self.generate_gwt15:
            cf.setHeight(1, 0, "100%")
            cf.setWidth(1, 0, "100%")
            cf.setAlignment(
                1, 0,
                HasHorizontalAlignment.ALIGN_CENTER,
                HasVerticalAlignment.ALIGN_MIDDLE,
            )
            self.panel.setWidget(0, 0, self.caption)
        else:
            row_labels = ['Top', 'Middle', 'Bottom']
            col_labels = ['Left', 'Center', 'Right']

            for r in range(3):
                rf.setStyleName(r, 'dialog%s' % row_labels[r])
                for c in range(3):
                    cf.setStyleName(r, c, 'dialog%s%s' % (row_labels[r],
                                                          col_labels[c]))
                    sp = SimplePanel()
                    sp.setStyleName('dialog%s%sInner' % (row_labels[r],
                                                         col_labels[c]))
                    self.panel.setWidget(r, c, sp)

            cf.setAlignment(
                1, 1,
                HasHorizontalAlignment.ALIGN_CENTER,
                HasVerticalAlignment.ALIGN_MIDDLE,
            )

            self.dialog_content = SimplePanel()
            self.dialog_content.setStyleName('dialogContent')

            self.panel.getWidget(0, 1).add(self.caption)
            self.panel.getWidget(1, 1).add(self.dialog_content)
            del kwargs['gwt15']

        # Finalize
        kwargs['StyleName'] = kwargs.get('StyleName', "gwt-DialogBox")
        PopupPanel.__init__(self, autoHide, modal, **kwargs)
        PopupPanel.setWidget(self, self.panel)

        self.centered = centered

    def onWindowResized(self, width, height):
        super(DialogBox, self).onWindowResized(width, height)
        if self.centered:
            self.centerBox()

    def show(self):
        super(DialogBox, self).show()
        if self.centered:
            self.centerBox()

    @classmethod
    def _getProps(self):
        return PopupPanel._getProps() + self._props

    def onEventPreview(self, event):
        # preventDefault on mousedown events, outside of the
        # dialog, to stop text-selection on dragging
        type = DOM.eventGetType(event)
        if type == 'mousedown':
            target = DOM.eventGetTarget(event)
            elem = self.caption.getElement()
            event_targets_popup = target and DOM.isOrHasChild(elem, target)
            if event_targets_popup:
                DOM.eventPreventDefault(event)
        return PopupPanel.onEventPreview(self, event)

    def getHTML(self):
        return self.caption.getHTML()

    def getText(self):
        return self.caption.getText()

    def setHTML(self, html):
        self.caption.setHTML(html)

    def setText(self, text):
        self.caption.setText(text)

    def onMouseDown(self, sender, x, y):
        self.dragging = True
        GlassWidget.show(self.caption)
        self.dragStartX = x
        self.dragStartY = y

    def onMouseEnter(self, sender):
        pass

    def onMouseLeave(self, sender):
        pass

    def onMouseMove(self, sender, x, y):
        if not self.dragging:
            return
        absX = x + self.getAbsoluteLeft()
        absY = y + self.getAbsoluteTop()
        self.setPopupPosition(absX - self.dragStartX,
                              absY - self.dragStartY)

    def onMouseUp(self, sender, x, y):
        self.endDragging()

    def onMouseGlassEnter(self, sender):
        pass

    def onMouseGlassLeave(self, sender):
        self.endDragging()

    def endDragging(self):
        if not self.dragging:
            return
        self.dragging = False
        GlassWidget.hide()

    def remove(self, widget):
        if self.child != widget:
            return False

        self.panel.remove(widget)
        self.child = None
        return True

    def doAttachChildren(self):
        PopupPanel.doAttachChildren(self)
        self.caption.onAttach()

    def doDetachChildren(self):
        PopupPanel.doDetachChildren(self)
        self.caption.onDetach()

    def setWidget(self, widget):
        if self.child is not None:
            if not self.generate_gwt15:
                self.panel.remove(self.child)
            else:
                self.dialog_content.remove(self.child)

        if widget is not None:
            if not self.generate_gwt15:
                self.panel.setWidget(1, 0, widget)
            else:
                self.dialog_content.setWidget(widget)

        self.child = widget

Factory.registerClass('pyjamas.ui.DialogBox', 'DialogBox', DialogBox)
