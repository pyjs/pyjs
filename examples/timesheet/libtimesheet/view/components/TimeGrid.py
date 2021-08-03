
# vim: set ts=4 sw=4 expandtab:

from libtimesheet.ApplicationConstants import Notification

from pyjamas.ui.VerticalPanel import VerticalPanel
from pyjamas.ui.FlexTable import FlexTable
from pyjamas.ui.Label import Label
from pyjamas.ui.TextBox import TextBox

from Grid import Grid

from libtimesheet.model.vo.TimeVO import TimeVO

class TimeGrid(FlexTable):

    columns = [("From", 5, 5),
               ("To", 5, 5),
               ("Project", None, 20),
               ("Description", None, 40),
              ]
    emptyTimeVO = TimeVO("", "", "", "")
    rows = 0
    currentRow = 0
    cols = 0
    currentCol = 0
    date = None
    dirty = False

    def __init__(self):
        try:
            FlexTable.__init__(self)
            self.cols = len(self.columns)
            self.addHeader()
            self.addRow()
            self.currentRow = self.rows
            self.addRow()
            self.getWidget(1, 0).setFocus(True)
        except:
            raise

    def getEntries(self):
        entries = []
        for row in range(1, self.rows+1):
            timeVO = TimeVO(\
                self.getWidget(row, 0).getText().strip(),
                self.getWidget(row, 1).getText().strip(),
                self.getWidget(row, 2).getText().strip(),
                self.getWidget(row, 3).getText().strip(),
               )
            if not timeVO.isEmpty():
                entries.append(timeVO)
        return entries

    def setEntries(self, entries):
        row = 0
        for timeVO in entries:
            row += 1
            if self.rows < row:
                self.addRow(timeVO)
            else:
                self.setRow(row, timeVO)
        while row < self.rows:
            self.deleteRow(self.rows)
        self.addRow()
        if self.rows == 1:
            self.addRow()
        self.setFocus()

    def setFocus(self):
        for row in range(1, self.rows):
            if not self.checkRow(row):
                break

    def selectCell(self, row, col):
        if col < 0:
            if row > 1:
                col = self.cols - 1
                row -= 1
            else:
                col = 0
        elif col >= self.cols:
            if row < self.rows:
                col = 0
                row += 1
            else:
                col = self.cols - 1
        if row < 1:
            row = 1
        elif row > self.rows:
            row = self.rows
        if self.currentRow == row and self.currentCol == col:
            self.getWidget(self.currentRow, self.currentCol).setFocus(True)
            return
        if (self.currentRow > row) or \
           (self.currentRow == row and self.currentCol > col):
            # We're moving up or to the left, just leave the current cell
            self.currentRow = row
            self.currentCol = col
            self.getWidget(self.currentRow, self.currentCol).setFocus(True)
            return
        # Now we're moving to new position, just make sure
        # that the previous cells are filled in correctly
        if not self.checkCell(self.currentRow, self.currentCol, True):
            # Nope. We won't move
            self.getWidget(self.currentRow, self.currentCol).setFocus(True)
            return
        if self.currentRow == row:
            # We're moving to the right
            self.currentRow = row
            self.currentCol = col
        else:
            # We're moving down
            if not self.checkRow(self.currentRow):
                # We cannot leave the current row
                self.getWidget(self.currentRow, self.currentCol).setFocus(True)
                return
            for r in range(self.currentRow, row - 1):
                if not self.checkRow(r):
                    # We cannot step over invalid rows
                    self.getWidget(self.currentRow, self.currentCol).setFocus(True)
                    return
            self.currentRow = row
            self.currentCol = col
            # Check for invalid cells left of the asked-for col
            for c in range(col):
                if not self.checkCell(row, c):
                    self.currentCol = c
                    break
            # Add a row if we're at the last row
            if self.currentRow == self.rows:
                self.addRow()

        if self.currentCol == 0:
            # Try to auto fill the new cell
            self.autoFill(self.currentRow, self.currentCol)
        elif self.currentCol == 2:
            # Try to auto fill the previous cell
            self.autoFill(self.currentRow, self.currentCol - 1)
        self.getWidget(self.currentRow, self.currentCol).setFocus(True)

    def addHeader(self):
        # HH:MM|HH:MM|Project|Description
        col = 0
        for label, maxLength, visibleLength in self.columns:
            self.setWidget(0, col, Label(label, wordWrap=False))
            col += 1

    def setRow(self, row, timeVO = None):
        if timeVO is None:
            timeVO = self.emptyTimeVO
        self.getWidget(row, 0).setText(timeVO.start)
        self.getWidget(row, 1).setText(timeVO.end)
        self.getWidget(row, 2).setText(timeVO.project)
        self.getWidget(row, 3).setText(timeVO.description)

    def addRow(self, timeVO = None):
        self.rows += 1
        col = -1
        for name, maxLength, visibleLength in self.columns:
            col += 1
            textBox = TextBox()
            textBox.setText("")
            textBox.col = col
            textBox.row = self.rows
            textBox.addChangeListener(self.checkValid)
            textBox.addKeyboardListener(self)
            textBox.addFocusListener(self)
            textBox.setName(name)
            if not maxLength is None:
                textBox.setMaxLength(maxLength)
            if not visibleLength is None:
                textBox.setVisibleLength(visibleLength)
            self.setWidget(self.rows, col, textBox)
        if not timeVO is None:
            self.setRow(self.rows, timeVO)

    def deleteRow(self, row):
        for col in range(self.getCellCount(row)):
            child = self.getWidget(row, col)
            if child is not None:
                self.removeWidget(child)
        self.rows -= 1

    def checkNumber(self, text, round = 1):
        text = text.strip()
        _text = text.lstrip("0")
        if _text == "":
            return "00"
        i = int(_text)
        if i >= 0 and i < 60:
            i = int(i / round) * round
            return "%02d" % i
        raise ValueError("Invalid format '%s'" % text)

    def checkHHMM(self, text):
        if text == "":
            return ""
        _text = text.split(':')
        if len(_text) <= 2:
            HH = self.checkNumber(_text[0])
            if len(_text) == 2:
                MM = self.checkNumber(_text[1], 15)
            else:
                MM = "00"
            return "%s:%s" % (HH, MM)
        raise ValueError("Invalid format '%s'" % text)


    def autoFill(self, row, col):
        widget = self.getWidget(row, col)
        if col == 0:
            timeFrom = self.getWidget(row, 0).getText()
            if timeFrom == "" and row > 1:
                timeFrom = self.getWidget(row-1, 1).getText()
                widget.setText(timeFrom)
        elif col == 1:
            timeFrom = self.getWidget(row, 0).getText().strip()
            _text = widget.getText().strip()
            if timeFrom == "" or timeFrom < _text:
                return
            try:
                HM = timeFrom.split(":")
                timeFromHH = int(HM[0])
                timeFromMM = int(HM[1])
                HM = _text.split(":")
                _textHH = int(HM[0])
                _textMM = int(HM[1])
            except:
                widget.setFocus(True)
                return
            _textHH += timeFromHH
            _textMM += timeFromMM + _textHH * 60
            _textHH = int(_textMM/60)
            _textMM -= _textHH * 60
            _text = "%02d:%02d" % (_textHH, _textMM)
            if _text != "00:00":
                widget.setText(_text)

    def checkCell(self, row, col, auto = False):
        widget = self.getWidget(row, col)
        if col in [0, 1]:
            try:
                text = widget.getText()
                _text = text.strip()
                if text !=  _text:
                    text = _text
                    widget.setText(text)
                _text = self.checkHHMM(text)
            except ValueError, e:
                widget.setFocus(True)
                return False
            if text == "":
                widget.setFocus(True)
                return False
            if text !=  _text:
                if auto:
                    widget.setText(_text)
                else:
                    return False
            return True
        elif col == 2:
            text = widget.getText()
            if len(text) == 0:
                widget.setFocus(True)
                return False
        return True

    def checkRow(self, row):
        for col in range(self.cols):
            if not self.checkCell(row, col):
                return False
        return True

    def checkValid(self, sender):
        self.selectCell(sender.row, sender.col)
        self.dirty = True
        return
        if sender.row != self.currentRow:
            if not self.checkRow(self.currentRow):
                return False
        return self.checkRow(sender.row)

    def onKeyUp(self, sender, keyCode, modifiers):
        currStatus = self.checkCell(self.currentRow, self.currentCol)
        if modifiers == 0:
            if keyCode == 37: #left
                if sender.getCursorPos() == 0:
                    self.selectCell(sender.row, sender.col - 1)
            elif keyCode == 38: #up
                self.selectCell(sender.row - 1, sender.col)
            elif keyCode == 39: #right
                if sender.getCursorPos() == len(sender.getText()):
                    self.selectCell(sender.row, sender.col + 1)
            elif keyCode == 40: #down
                self.selectCell(sender.row + 1, sender.col)
            elif keyCode == 13: #enter
                self.selectCell(sender.row, sender.col + 1)
            else:
                self.dirty = True
        else:
            self.dirty = True

    def onKeyDown(self, sender, keyCode, modifiers):
        pass

    def onKeyPress(self, sender, keyCode, modifiers):
        pass

    def onFocus(self, sender):
        if sender.row != self.currentRow or \
           sender.col != self.currentCol:
            self.selectCell(sender.row, sender.col)

    def onLostFocus(self, sender):
        pass


