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
from pyjamas import DOM
from pyjamas import Factory

from pyjamas.ui.Panel import Panel

class ComplexPanel(Panel):
    """
        Superclass for widgets with multiple children.
    """
    def add(self, widget, container=None):
        if container is not None:
            self.insert(widget, container, self.getWidgetCount())
        else:
            self.insert(widget, self.getWidgetCount())

    def insert(self, widget, container, beforeIndex=None):
        """ has two modes of operation:
            widget, beforeIndex
            widget, container, beforeIndex.
            if beforeIndex argument is not given, the 1st mode is assumed.
            this technique is less costly than using *args.
        """
        if widget.getParent() == self:
            return

        if beforeIndex is None:
            beforeIndex = container
            container = self.getElement()

        self.adopt(widget, container, beforeIndex)
        self.children.insert(beforeIndex, widget)

    def remove(self, widget):
        if isinstance(widget, int):
            widget = self.getWidget(widget)
        if widget not in self.getChildren():
            return False

        self.disown(widget)
        self.getChildren().remove(widget)

        return True


Factory.registerClass('pyjamas.ui.ComplexPanel', 'ComplexPanel', ComplexPanel)

