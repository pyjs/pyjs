"""
    Horizontal Split Panel: Left and Right layouts with a movable splitter.

/*
 * Copyright 2008 Google Inc.
 * Copyright 2009 Luke Kenneth Casson Leighton <lkcl@lkcl.net>
 *
 * Licensed under the Apache License, Version 2.0 (the "License") you may not
 * use this file except in compliance with the License. You may obtain a copy of
 * the License at
 *
 * http:#www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
 * License for the specific language governing permissions and limitations under
 * the License.
 */
"""

class ImplHorizontalSplitPanel:
    """ The IE6 implementation for horizontal split panels.
    """

    def __init__(self, panel):

        self.panel = panel
        self.isResizeInProgress = False
        self.splitPosition = 0

        elem = panel.getElement()

        # Prevents inherited text-align settings from interfering with the
        # panel's layout. The setting we choose must be bidi-sensitive,
        # as left-alignment is the default with LTR directionality, and
        # right-alignment is the default with RTL directionality.
        if True: # TODO (LocaleInfo.getCurrentLocale().isRTL()) {
            DOM.setStyleAttribute(elem, "textAlign", "right")
        else:
            DOM.setStyleAttribute(elem, "textAlign", "left")

        DOM.setStyleAttribute(elem, "position", "relative")

        # Technically, these are snapped to the top and bottom, but IE doesn't
        # provide a reliable way to make that happen, so a resize listener is
        # wired up to control the height of these elements.
        self.panel.addAbsolutePositoning(panel.getWidgetElement(0))
        self.panel.addAbsolutePositoning(panel.getWidgetElement(1))
        self.panel.addAbsolutePositoning(panel.getSplitElement())

        self.panel.expandToFitParentUsingPercentages(panel.container)

        if True: # TODO (LocaleInfo.getCurrentLocale().isRTL()):
        # Snap the left pane to the left edge of the container. We
        # only need to do this when layout is RTL if we don't, the
        # left pane will overlap the right pane.
            panel.setLeft(panel.getWidgetElement(0), "0px")

    def onAttach(self):
        self.addResizeListener(self.panel.container)
        self.onResize()

    def onDetach(self):
        DOM.setElementAttribute(self.panel.container, "onresize", None)

    def onTimer(self, sender):
        self.setSplitPositionUsingPixels(       self.splitPosition)
        self.isResizeInProgress = False

    def onSplitterResize(self, px):
        if not self.isResizeInProgress:
            self.isResizeInProgress = True
            Timer(self, 20)
        self.splitPosition = px

    def setSplitPositionUsingPixels(self, px):
        if True: # TODO (LocaleInfo.getCurrentLocale().isRTL()) {
            splitElem = self.panel.getSplitElement()

            rootElemWidth = self.panel.getOffsetWidth(self.panel.container)
            splitElemWidth = self.panel.getOffsetWidth(splitElem)

            # This represents an invalid state where layout is incomplete. This
            # typically happens before DOM attachment, but I leave it here as a
            # precaution because negative width/height style attributes produce
            # errors on IE.
            if (rootElemWidth < splitElemWidth):
                return

            # Compute the new right side width.
            newRightWidth = rootElemWidth - px - splitElemWidth

            # Constrain the dragging to the physical size of the panel.
            if (px < 0):
                px = 0
                newRightWidth = rootElemWidth - splitElemWidth
            elif (newRightWidth < 0):
                px = rootElemWidth - splitElemWidth
                newRightWidth = 0

            # Set the width of the right side.
            self.panel.setElemWidth(self.panel.getWidgetElement(1), newRightWidth + "px")

            # Move the splitter to the right edge of the left element.
            self.panel.setLeft(splitElem, px + "px")

            # Update the width of the left side
            if (px == 0):

              # This takes care of a qurky RTL layout bug with IE6.
              # During DOM construction and layout, onResize events
              # are fired, and this method is called with px == 0.
              # If one tries to set the width of the 0 element to
              # before layout completes, the 1 element will
              # appear to be blanked out.

                DeferredCommand.add(self)
            else:
                self.panel.setElemWidth(self.panel.getWidgetElement(0), px + "px")

        else:
            self._setSplitPositionUsingPixels(px)

    def execute(self):
        self.panel.setElemWidth(self.panel.getWidgetElement(0), "0px")

    def updateRightWidth(self, rightElem, newRightWidth):
        self.panel.setElemWidth(rightElem, newRightWidth + "px")

    def addResizeListener(self, container):

        resizefn = getattr(self, "onResize")

        JS("""
            @{{container}}['onresize'] = function() {
               @{{resizefn}}();
                                      }
        """)

    def onResize(self):
      leftElem = self.panel.getWidgetElement(0)
      rightElem = self.panel.getWidgetElement(1)

      height = self.panel.getOffsetHeight(self.panel.container) + "px"
      self.panel.setElemHeight(rightElem, height)
      self.panel.setElemHeight(self.panel.getSplitElement(), height)
      self.panel.setElemHeight(leftElem, height)
      self.setSplitPositionUsingPixels(self.panel.getOffsetWidth(leftElem))

