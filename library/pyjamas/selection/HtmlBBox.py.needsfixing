"""
Copyright 2011 John Kozura

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy of
the License at

http:#www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations under
the License.
"""



from pyjamas import DOM
from pyjamas.ui.Widget import Widget



"""*
Represents a bounding box, and methods for finding the bounding box of
elements and ranges.

@author John Kozura
"""
class HtmlBBox:
    int self.m_x, self.m_y, self.m_width, self.m_height

    def __init__(self, x, y, width, height):
        """
        Create a bounding box based on x/y and width/height

        @param x
        @param y
        @param width
        @param height
        """
        self.m_x = x
        self.m_y = y
        self.m_width = width
        self.m_height = height


    def __init__(self, ele):
        """
        Create a location based on an element's bounding box

        @param ele Element to initialize bounding box with
        """
        this(ele.getAbsoluteLeft(), ele.getAbsoluteTop(),
        ele.getOffsetWidth(), ele.getOffsetHeight())


    def expand(self, bb):
        """
        Expand this box by the given bounding box

        @param bb box to use to expand this one
        """
        if bb is not None:
            self.m_x = Math.min(self.m_x, bb.getAbsoluteLeft())
            self.m_y = Math.min(self.m_y, bb.getAbsoluteTop())
            self.m_width = Math.max(getAbsoluteRight(), bb.getAbsoluteRight()) - self.m_x
            self.m_height = Math.max(getAbsoluteBottom(),
            bb.getAbsoluteBottom()) - self.m_y



    def getBoundingBox(self, ele):
        """
        Create a bounding box the size of the given element

        @param ele Element to create bounding box around
        @return a bounding box
        """
        return HtmlBBox(ele)


    def getBoundingBox(self, rng):
        """
        Create a bounding box the size of the given range

        @param range Range to create bounding box around
        @return a bounding box
        """
        HtmlBBox res

        if rng.getStartPoint().getTextNode() == rng.getEndPoint().getTextNode():
            res = getBoundingBox(rng.getStartPoint().getTextNode(),
            rng.getStartPoint().getOffset(),
            rng.getEndPoint().getOffset())

        else:
            res = getBoundingBox(rng.getStartPoint(), True)
            res.expand(getBoundingBox(rng.getEndPoint(), False))

            # Make sure the range encompasses all of the text nodes within
            # the range as well
            List<Text> texts = rng.getSelectedTextElements()
            for int i = 1; i < (texts.size() - 1); i++:
                res.expand(getBoundingBox(texts.get(i)))


        return res


    def getBoundingBox(self, textNode):
        """
        Create a bounding box the size of the given text node.  Note that this
        temporarily modifies the document to surround this node with a Span.

        @param textNode Text to create bounding box around
        @return a bounding box
        """
        Element el = DOM.createSpan()
        surround(textNode, el)
        HtmlBBox res = HtmlBBox(el)
        unSurround(el)
        return res


    def getBoundingBox(self, textNode, offset):
        """
        Create a bounding box around the single character at the offset given
        within a text node.  If the offset is at the end of the text, the
        bounding box is a point.  Temporarily modifies the document as indicated
        in getBoundingBox(textNode, offset1, offset2)

        @param textNode Text node to find character in
        @param offset offset of the character
        @return a bounding box
        """
        return getBoundingBox(textNode, offset, offset if offset == textNode.getLength() else offset+1)


    def getBoundingBox(self, textNode, offset1, offset2):
        """
        Create a bounding box the size of the text between the two offsets of
        the given textNode.  Note that this temporarily modifies the document
        to excise the sub-text into its own span element, which is then used
        to generate the bounding box.

        @param textNode Text to create bounding box around
        @param offset1 Starting offset to get bounding box from
        @param offset2 Ending offset to get bounding box from

        @return a bounding box
        """
        HtmlBBox res

        String text = textNode.getData()
        int len = text.length()
        if (offset1 == 0)  and  (offset2 == len):
            # Shortcut
            return getBoundingBox(textNode)

        if (offset2 > len)  or  (offset1 > offset2):
            return None


        # If this is a cursor, we still need to outline one character
        boolean isCursor = (offset1 == offset2)
        boolean posRight = False
        if isCursor:
            if offset1 == len:
                offset1--
                posRight = True

            else:
                offset2++



        # Create 2 or 3 spans of this text, so we can measure
        List<Element> nodes = ArrayList<Element>(3)
        Element tmpSpan, measureSpan
        if offset1 > 0:
            # First
            tmpSpan = DOM.createSpan()
            tmpSpan.setInnerHTML(text.substring(0, offset1))
            nodes.add(tmpSpan)


        # Middle, the one we measure
        measureSpan = DOM.createSpan()
        measureSpan.setInnerHTML(text.substring(offset1, offset2))
        nodes.add(measureSpan)

        if offset2 < (len - 1):
            # Last
            tmpSpan = DOM.createSpan()
            tmpSpan.setInnerHTML(text.substring(offset2 + 1))
            nodes.add(tmpSpan)


        Node parent = textNode.getParentNode()

        for Node node : nodes:
            parent.insertBefore(node, textNode)


        parent.removeChild(textNode)

        if isCursor:
            # Just make a 0-width version, depending on left or right
            res = HtmlBBox(measureSpan.getAbsoluteLeft() +
            (measureSpan.getOffsetWidth() if posRight else 0),
            measureSpan.getAbsoluteTop(),
            0,
            measureSpan.getOffsetHeight())

        else:
            res = HtmlBBox(measureSpan)


        parent.insertBefore(textNode, nodes.get(0))

        for Node node : nodes:
            parent.removeChild(node)


        return res


    def getBoundingBox(self, endPoint):
        """
        Create a bounding box around the single character at the rangeEndPoint
        given.  If the offset is at the end of the text, the
        bounding box is a point.  Temporarily modifies the document as indicated
        in getBoundingBox(textNode, offset1, offset2)

        @param endPoint End point to find character in
        @return a bounding box
        """
        return getBoundingBox(endPoint.getTextNode(), endPoint.getOffset())


    def getBoundingBox(self, endPoint, asStart):
        """
        Create a bounding box around the text of the rangeEndPoint specified,
        either to the end or the beginning of the endPoint's text node.
        Temporarily modifies the document as indicated in
        getBoundingBox(textNode, offset1, offset2)

        @param endPoint End point to find character in
        @param asStart Whether to get text from here to end (True) or from start
                       to here (False)
        @return a bounding box
        """
        return getBoundingBox(endPoint.getTextNode(),
        endPoint.getOffset() if asStart else 0,
        endPoint.getTextNode().getLength() if asStart else endPoint.getOffset())


    def getBoundingBox(self, wid):
        """
        Create a bounding box around a widget.

        @param wid Widget to get bounding box of
        @return a bounding box
        """
        return getBoundingBox(wid.getElement())


    # Some random DOM utility functions

    def getChildIndex(self, child):
        """
        Determine the index of a node within its parent

        @param child A node to determine the index of
        @return index of the node, or -1 on failure
        """
        int res = -1
        Node parent = child.getParentNode()
        if parent is not None:
            for int i = 0; i < parent.getChildCount(); i++:
                if child == parent.getChild(i):
                    res = i
                    break



        return res


    def unSurround(self, parent):
        """
        Move all children of this element up into its place, and remove the
        element.

        @param parent element to replace with its children
        """
        Node superParent = parent.getParentNode()
        Node child
        while (child = parent.getFirstChild()) is not None:
            parent.removeChild(child)
            superParent.insertBefore(child, parent)

        superParent.removeChild(parent)


    def surround(self, toChild, newParent):
        """
        Move a node inside of a parent element, maintaining it within the DOM

        @param toChild Node to make into a child
        @param newParent Element to make into a parent in its place
        """
        toChild.getParentElement().insertBefore(newParent, toChild)
        newParent.appendChild(toChild)



    int getAbsoluteLeft() {return self.m_x;}
    int getAbsoluteTop() {return self.m_y;}
    int getAbsoluteRight() {return self.m_x + self.m_width;}
    int getAbsoluteBottom() {return self.m_y + self.m_height;}
    int getOffsetWidth() {return self.m_width;}
    int getOffsetHeight() {return self.m_height;}
    int getCenterX() {return self.m_x + self.m_width / 2;}
    int getCenterY() {return self.m_y + self.m_height / 2;}

    @Override
    def equals(self, o):
        try:
            HtmlBBox comp = (HtmlBBox)o

            return (comp.getAbsoluteLeft() == self.m_x)  and
            (comp.getAbsoluteTop() == self.m_y)  and
            (comp.getOffsetHeight() == self.m_height)  and
            (comp.getOffsetWidth() == self.m_width)

        catch (Exception ex) {}

        return False



