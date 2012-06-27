# Copyright 2006 James Tauber and contributors
# Copyright 2009 Luke Kenneth Casson Leighton
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

class HasHorizontalAlignment:
    ALIGN_LEFT = "left"
    ALIGN_CENTER = "center"
    ALIGN_RIGHT = "right"

class HasVerticalAlignment:
    ALIGN_TOP = "top"
    ALIGN_MIDDLE = "middle"
    ALIGN_BOTTOM = "bottom"

class HasAlignment:
    ALIGN_BOTTOM = "bottom"
    ALIGN_MIDDLE = "middle"
    ALIGN_TOP = "top"
    ALIGN_CENTER = "center"
    ALIGN_LEFT = "left"
    ALIGN_RIGHT = "right"

PROP_NAME = 0
PROP_DESC = 1
PROP_FNAM = 2
PROP_TYPE = 3

ELPROP_NAME = 0
ELPROP_DESC = 1
ELPROP_FNAM = 2
ELPROP_TYPE = 3
ELPROP_DFLT = 4

def get_list_columns(props, cols):
    res = []
    for p in props:
        r = ()
        for idx in cols:
            r.append(p[idx])
        res.append(r)
    return res

def get_prop_widget_function_names(props):
    return get_list_columns(props, (PROP_FNAM,))

class Applier(object):

    _props = []
    _elem_props = []

    def __init__(self, **kwargs):
        """ use this to apply properties as a dictionary, e.g.::

                x = klass(..., StyleName='class-name')

            will do::

                x = klass(...)
                x.setStyleName('class-name')

            and::

                x = klass(..., Size=("100%", "20px"), Visible=False)

            will do::

                x = klass(...)
                x.setSize("100%", "20px")
                x.setVisible(False)
        """

        self.applyValues(**kwargs)

    def applyValues(self, **kwargs):

        for (prop, args) in kwargs.items():
            fn = getattr(self, "set%s" % prop, None)
            if not fn:
                raise Exception("setter function for %s does not exist in %s" % (prop, self.__class__.__name__))
            args = kwargs[prop]
            if isinstance(args, tuple):
                fn(*args)
            else:
                fn(args)

    def retrieveValues(self, *args):
        """ use this function to obtain a dictionary of properties, as
            stored in getXXX functions.
        """

        res = {}
        for prop in args:
            fn = getattr(self, "get%s" % prop, None)
            if not fn:
                raise Exception("getter function for %s does not exist" % prop)
            res[prop] = fn()

        return res

    @classmethod
    def _getProps(self):
        return self._props

    @classmethod
    def _getElementProps(self):
        return self._elem_props

    def setDefaults(self, defaults):
        divs = self.retrieveValues(wnames)
        for p in get_prop_widget_function_names(self._getProps()):
            defaults[p[PROP_NAME]] = divs[p[PROP_FNAM]]

    def updateInstance(self, app_context):
        args = {}
        for p in self._getProps():
            val = app_context.getAppProperty(p[0])
            convert_to_type = p[PROP_TYPE]
            if convert_to_type:
                 val = convert_to_type(val) if val else None
            args[p[PROP_FNAM]] = val

        self.applyValues(**args)

    def setElementProperties(self, context, elemProps):
        args = {}
        for p in self._getElementProps():
            if elemProps.has_key(p):
                val = elemProps[p]
                convert_to_type = p[ELPROP_TYPE]
                if convert_to_type:
                     val = convert_to_type(val) if val else None
            else:
                val = p[ELPROP_DFLT]
                if val is None:
                    continue
            args[p[ELPROP_FNAM]] = (context, val,)

        self.applyValues(**args)

