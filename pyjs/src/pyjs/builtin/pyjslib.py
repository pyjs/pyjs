# Copyright 2006 James Tauber and contributors
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

# iteration from Bob Ippolito's Iteration in JavaScript

# must declare import _before_ importing sys

from __pyjamas__ import INT, JS, setCompilerOptions, debugger

setCompilerOptions("noDebug", "noBoundMethods", "noDescriptors", "noGetattrSupport", "noAttributeChecking", "noSourceTracking", "noLineTracking", "noStoreSource")

platform = JS("$pyjs['platform']")
sys = None
dynamic = None
Ellipsis = None
JS("""
var $max_float_int = 1;
for (var i = 0; i < 1000; i++) {
    $max_float_int *= 2;
    if ($max_float_int + 1 == $max_float_int) {
        break;
    }
}
$max_int = 0x7fffffff;
$min_int = -0x80000000;
""")

_handle_exception = JS("""function(err) {
    $pyjs['loaded_modules']['sys']['save_exception_stack']();

    if (!$pyjs['in_try_except']) {
        var $pyjs_msg = $pyjs['loaded_modules']['sys']['_get_traceback'](err);
        $pyjs['__active_exception_stack__'] = null;
        @{{debugReport}}($pyjs_msg);
    }
    throw err;
};
""")

def _create_class(clsname, bases=None, methods=None):
    # Creates a new class, emulating parts of Python's new-style classes
    # TODO: We should look at __metaclass__, but for now we only
    # handle the fallback to __class__
    if bases and hasattr(bases[0], '__class__') and hasattr(bases[0], '__new__'):
        main_base = bases[0]
        return main_base.__class__(clsname, bases, methods)
    return type(clsname, bases, methods)

def type(clsname, bases=None, methods=None):
    if bases is None and methods is None:
        # First check for str and bool, since these are not implemented
        # as real classes, but instances do have a __class__ method
        if isinstance(clsname, str):
            return str
        if isinstance(clsname, bool):
            return bool
        if hasattr(clsname, '__class__'):
            return clsname.__class__
        if isinstance(clsname, int):
            return int
        if isinstance(clsname, float):
            return float
        if JS("typeof @{{clsname}} == 'number'"):
            return float
        if JS("@{{clsname}} == null"):
            return NoneType
        if JS("typeof @{{clsname}} == 'function'"):
            return FunctionType
        raise ValueError("Cannot determine type for %r" % clsname)

    # creates a class, derived from bases, with methods and variables
    JS(" var mths = {}; ")
    if methods:
        for k in methods.keys():
            mth = methods[k]
            JS(" @{{!mths}}[@{{!k}}] = @{{mth}}; ")

    JS(" var bss = null; ")
    if bases:
        JS("@{{!bss}} = @{{bases}}['__array'];")
    JS(" return $pyjs_type(@{{clsname}}, @{{!bss}}, @{{!mths}}); ")

class object:

    def __setattr__(self, name, value):
        JS("""
        if (typeof @{{name}} != 'string') {
            throw @{{TypeError}}("attribute name must be string");
        }
        if (attrib_remap['indexOf'](@{{name}}) >= 0) {
            @{{name}} = '$$' + @{{name}};
        }
        if (typeof @{{self}}[@{{name}}] != 'undefined'
            && @{{self}}['__is_instance__']
            && @{{self}}[@{{name}}] !== null
            && typeof @{{self}}[@{{name}}]['__set__'] == 'function') {
            @{{self}}[@{{name}}]['__set__'](@{{self}}, @{{value}});
        } else {
            @{{self}}[@{{name}}] = @{{value}};
        }
        """)

# The __str__ method is not defined as 'def __str__(self):', since
# we might get all kind of weird invocations. The __str__ is sometimes
# called from toString()
object.__str__ = JS("""function (self) {
    if (typeof self == 'undefined') {
        self = this;
    }
    var s;
    if (self['__is_instance__'] === true) {
        s = "instance of ";
    } else if (self['__is_instance__'] === false) {
        s = "class ";
    } else {
        s = "javascript " + typeof self + " ";
    }
    if (self['__module__']) {
        s += self['__module__'] + ".";
    }
    if (typeof self['__name__'] != 'undefined') {
        return s + self['__name__'];
    }
    return s + "<unknown>";
}""")


class basestring(object):
    pass

class TypeClass:
    def __repr__(cls):
        return "<type '%s'>" % cls.__name__

class NoneType(TypeClass):
    pass
class ModuleType(TypeClass):
    pass
class FunctionType(TypeClass):
    pass
class CodeType(TypeClass):
    pass
class TracebackType(TypeClass):
    pass
class FrameType(TypeClass):
    pass
class EllipsisType(TypeClass):
    def __new__(cls):
        if Ellipsis is None:
            return object.__new__(cls)
        else:
            return Ellipsis
    def __repr__(self):
        return 'Ellipsis'
    def __str__(self):
        return 'Ellipsis'

def op_is(a,b):
    JS("""
    if (@{{a}} === @{{b}}) return true;
    if (@{{a}} !== null && @{{b}} !== null) {
        switch ((@{{a}}['__number__'] << 8) | @{{b}}['__number__']) {
            case 0x0101:
                return @{{a}} == @{{b}};
            case 0x0202:
                return @{{a}}['__v'] == @{{b}}['__v'];
            case 0x0404:
                return @{{a}}['__cmp__'](@{{b}}) == 0;
        }
    }
    return false;
""")

def op_eq(a,b):
    # All 'python' classes and types are implemented as objects/functions.
    # So, for speed, do a typeof X / X.__cmp__  on a/b.
    # Checking for the existance of .__cmp__ is expensive when it doesn't exist
    #setCompilerOptions("InlineEq")
    #return a == b
    JS("""
    if (@{{a}} === null) {
        if (@{{b}} === null) return true;
        return false;
    }
    if (@{{b}} === null) {
        return false;
    }
    if (@{{a}} === @{{b}}) {
        if (@{{a}}['__is_instance__'] === false &&
            @{{b}}['__is_instance__'] === false) {
            return true;
        }
    }
    switch ((@{{a}}['__number__'] << 8) | @{{b}}['__number__']) {
        case 0x0101:
        case 0x0401:
            return @{{a}} == @{{b}};
        case 0x0102:
            return @{{a}} == @{{b}}['__v'];
        case 0x0201:
            return @{{a}}['__v'] == @{{b}};
        case 0x0202:
            return @{{a}}['__v'] == @{{b}}['__v'];
        case 0x0104:
        case 0x0204:
            @{{a}} = new @{{long}}(@{{a}}['valueOf']());
        case 0x0404:
            return @{{a}}['__cmp__'](@{{b}}) == 0;
        case 0x0402:
            return @{{a}}['__cmp__'](new @{{long}}(@{{b}}['valueOf']())) == 0;
    }
    if (typeof @{{a}} == 'object' || typeof @{{a}} == 'function') {
        if (typeof @{{a}}['__eq__'] == 'function') {
            if (typeof @{{b}}['__eq__'] != 'function') {
                return false;
            }
            if (@{{a}}['__eq__'] === @{{b}}['__eq__']) {
                return @{{a}}['__eq__'](@{{b}});
            }
            if (@{{_isinstance}}(@{{a}}, @{{b}})) {
                return @{{a}}['__eq__'](@{{b}});
            }
            return false;
        }
        if (typeof @{{a}}['__cmp__'] == 'function') {
            if (typeof @{{b}}['__cmp__'] != 'function') {
                return false;
            }
            if (@{{a}}['__cmp__'] === @{{b}}['__cmp__']) {
                return @{{a}}['__cmp__'](@{{b}}) == 0;
            }
            if (@{{_isinstance}}(@{{a}}, @{{b}})) {
                return @{{a}}['__cmp__'](@{{b}}) == 0;
            }
            return false;
        }
    } else if (typeof @{{b}} == 'object' || typeof @{{b}} == 'function') {
        if (typeof @{{b}}['__eq__'] == 'function') {
            if (@{{_isinstance}}(@{{a}}, @{{b}})) {
                return @{{b}}['__eq__'](@{{a}});
            }
            return false;
        }
        if (typeof @{{b}}['__cmp__'] == 'function') {
            // typeof bXXX['__cmp__'] != 'function'
            // aXXX['__cmp__'] !== bXXX['__cmp__']
            if (@{{_isinstance}}(@{{a}}, @{{b}})) {
                return @{{b}}['__cmp__'](@{{a}}) == 0;
            }
            return false;
        }
    }
    return @{{a}} == @{{b}};
    """)

def op_uadd(v):
    JS("""
    switch (@{{v}}['__number__']) {
        case 0x01:
        case 0x02:
        case 0x04:
            return @{{v}};
    }
    if (@{{v}}!== null) {
        if (typeof @{{v}}['__pos__'] == 'function') return @{{v}}['__pos__']();
    }
""")
    raise TypeError("bad operand type for unary +: '%r'" % v)

def op_usub(v):
    JS("""
    switch (@{{v}}['__number__']) {
        case 0x01:
            return -@{{v}};
        case 0x02:
            return new @{{int}}(-@{{v}});
    }
    if (@{{v}}!== null) {
        if (typeof @{{v}}['__neg__'] == 'function') return @{{v}}['__neg__']();
    }
""")
    raise TypeError("bad operand type for unary -: '%r'" % v)

def __op_add(x, y):
    JS("""
        return (typeof (@{{x}})==typeof (@{{y}}) &&
                (typeof @{{x}}=='number'||typeof @{{x}}=='string')?
                @{{x}}+@{{y}}:
                @{{op_add}}(@{{x}},@{{y}}));
    """)

def op_add(x, y):
    JS("""
    if (@{{x}}!== null && @{{y}}!== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0101:
            case 0x0104:
            case 0x0401:
                return @{{x}}+ @{{y}};
            case 0x0102:
                return @{{x}}+ @{{y}}['__v'];
            case 0x0201:
                return @{{x}}['__v'] + @{{y}};
            case 0x0202:
                return new @{{int}}(@{{x}}['__v'] + @{{y}}['__v']);
            case 0x0204:
                return (new @{{long}}(@{{x}}['__v']))['__add'](@{{y}});
            case 0x0402:
                return @{{x}}['__add'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__add'](@{{y}});
        }
        if (!@{{x}}['__number__']) {
            if (typeof @{{x}}== 'string' && typeof @{{y}}== 'string') return @{{x}}+ @{{y}};
            if (   !@{{y}}['__number__']
                && @{{x}}['__mro__']['length'] > @{{y}}['__mro__']['length']
                && @{{isinstance}}(@{{x}}, @{{y}})
                && typeof @{{x}}['__add__'] == 'function')
                return @{{y}}['__add__'](@{{x}});
            if (typeof @{{x}}['__add__'] == 'function') return @{{x}}['__add__'](@{{y}});
        }
        if (!@{{y}}['__number__'] && typeof @{{y}}['__radd__'] == 'function') return @{{y}}['__radd__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for +: '%r', '%r'" % (x, y))

def __op_sub(x, y):
    JS("""
        return (typeof (@{{x}})==typeof (@{{y}}) &&
                (typeof @{{x}}=='number'||typeof @{{x}}=='string')?
                @{{x}}-@{{y}}:
                @{{op_sub}}(@{{x}},@{{y}}));
    """)

def op_sub(x, y):
    JS("""
    if (@{{x}}!== null && @{{y}}!== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0101:
            case 0x0104:
            case 0x0401:
                return @{{x}}- @{{y}};
            case 0x0102:
                return @{{x}}- @{{y}}['__v'];
            case 0x0201:
                return @{{x}}['__v'] - @{{y}};
            case 0x0202:
                return new @{{int}}(@{{x}}['__v'] - @{{y}}['__v']);
            case 0x0204:
                return (new @{{long}}(@{{x}}['__v']))['__sub'](@{{y}});
            case 0x0402:
                return @{{x}}['__sub'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__sub'](@{{y}});
        }
        if (!@{{x}}['__number__']) {
            if (   !@{{y}}['__number__']
                && @{{x}}['__mro__']['length'] > @{{y}}['__mro__']['length']
                && @{{isinstance}}(@{{x}}, @{{y}})
                && typeof @{{x}}['__sub__'] == 'function')
                return @{{y}}['__sub__'](@{{x}});
            if (typeof @{{x}}['__sub__'] == 'function') return @{{x}}['__sub__'](@{{y}});
        }
        if (!@{{y}}['__number__'] && typeof @{{y}}['__rsub__'] == 'function') return @{{y}}['__rsub__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for -: '%r', '%r'" % (x, y))

def op_floordiv(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0101:
            case 0x0104:
            case 0x0401:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return Math['floor'](@{{x}} / @{{y}});
            case 0x0102:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return Math['floor'](@{{x}} / @{{y}}['__v']);
            case 0x0201:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return Math['floor'](@{{x}}['__v'] / @{{y}});
            case 0x0202:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('integer division or modulo by zero');
                return new @{{int}}(Math['floor'](@{{x}}['__v'] / @{{y}}['__v']));
            case 0x0204:
                return (new @{{long}}(@{{x}}['__v']))['__floordiv'](@{{y}});
            case 0x0402:
                return @{{x}}['__floordiv'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__floordiv'](@{{y}});
        }
        if (!@{{x}}['__number__']) {
            if (   !@{{y}}['__number__']
                && @{{x}}['__mro__']['length'] > @{{y}}['__mro__']['length']
                && @{{isinstance}}(@{{x}}, @{{y}})
                && typeof @{{x}}['__floordiv__'] == 'function')
                return @{{y}}['__floordiv__'](@{{x}});
            if (typeof @{{x}}['__floordiv__'] == 'function') return @{{x}}['__floordiv__'](@{{y}});
        }
        if (!@{{y}}['__number__'] && typeof @{{y}}['__rfloordiv__'] == 'function') return @{{y}}['__rfloordiv__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for //: '%r', '%r'" % (x, y))

def op_div(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0101:
            case 0x0104:
            case 0x0401:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return @{{x}} / @{{y}};
            case 0x0102:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return @{{x}} / @{{y}}['__v'];
            case 0x0201:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return @{{x}}['__v'] / @{{y}};
            case 0x0202:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return new @{{int}}(@{{x}}['__v'] / @{{y}}['__v']);
            case 0x0204:
                return (new @{{long}}(@{{x}}['__v']))['__div'](@{{y}});
            case 0x0402:
                return @{{x}}['__div'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__div'](@{{y}});
        }
        if (!@{{x}}['__number__']) {
            if (   !@{{y}}['__number__']
                && @{{x}}['__mro__']['length'] > @{{y}}['__mro__']['length']
                && @{{isinstance}}(@{{x}}, @{{y}})
                && typeof @{{x}}['__div__'] == 'function')
                return @{{y}}['__div__'](@{{x}});
            if (typeof @{{x}}['__div__'] == 'function') return @{{x}}['__div__'](@{{y}});
        }
        if (!@{{y}}['__number__'] && typeof @{{y}}['__rdiv__'] == 'function') return @{{y}}['__rdiv__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for /: '%r', '%r'" % (x, y))

def op_truediv(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0101:
            case 0x0104:
            case 0x0401:
            case 0x0204:
            case 0x0402:
            case 0x0404:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return @{{x}} / @{{y}};
            case 0x0102:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return @{{x}} / @{{y}}['__v'];
            case 0x0201:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return @{{x}}['__v'] / @{{y}};
            case 0x0202:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return @{{x}}['__v'] / @{{y}}['__v'];
        }
        if (!@{{x}}['__number__']) {
            if (   !@{{y}}['__number__']
                && @{{x}}['__mro__']['length'] > @{{y}}['__mro__']['length']
                && @{{isinstance}}(@{{x}}, @{{y}})
                && typeof @{{x}}['__truediv__'] == 'function')
                return @{{y}}['__truediv__'](@{{x}});
            if (typeof @{{x}}['__truediv__'] == 'function') return @{{x}}['__truediv__'](@{{y}});
        }
        if (!@{{y}}['__number__'] && typeof @{{y}}['__rtruediv__'] == 'function') return @{{y}}['__rtruediv__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for /: '%r', '%r'" % (x, y))

def op_mul(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0101:
            case 0x0104:
            case 0x0401:
                return @{{x}} * @{{y}};
            case 0x0102:
                return @{{x}} * @{{y}}['__v'];
            case 0x0201:
                return @{{x}}['__v'] * @{{y}};
            case 0x0202:
                return new @{{int}}(@{{x}}['__v'] * @{{y}}['__v']);
            case 0x0204:
                return (new @{{long}}(@{{x}}['__v']))['__mul'](@{{y}});
            case 0x0402:
                return @{{x}}['__mul'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__mul'](@{{y}});
        }
        if (!@{{x}}['__number__']) {
            if (   !@{{y}}['__number__']
                && @{{x}}['__mro__']['length'] > @{{y}}['__mro__']['length']
                && @{{isinstance}}(@{{x}}, @{{y}})
                && typeof @{{x}}['__mul__'] == 'function')
                return @{{y}}['__mul__'](@{{x}});
            if (typeof @{{x}}['__mul__'] == 'function') return @{{x}}['__mul__'](@{{y}});
        }
        if (!@{{y}}['__number__'] && typeof @{{y}}['__rmul__'] == 'function') return @{{y}}['__rmul__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for *: '%r', '%r'" % (x, y))

def op_mod(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0101:
            case 0x0104:
            case 0x0401:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                var v = @{{x}} % @{{y}};
                return (v < 0 && @{{y}} > 0 ? v + @{{y}} : v);
            case 0x0102:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('float divmod()');
                var v = @{{x}} % @{{y}}['__v'];
                return (v < 0 && @{{y}}['__v'] > 0 ? v + @{{y}}['__v'] : v);
            case 0x0201:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                var v = @{{x}}['__v'] % @{{y}};
                return (v < 0 && @{{y}}['__v'] > 0 ? v + @{{y}}['__v'] : v);
            case 0x0202:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('integer division or modulo by zero');
                var v = @{{x}}['__v'] % @{{y}}['__v'];
                return new @{{int}}(v < 0 && @{{y}}['__v'] > 0 ? v + @{{y}}['__v'] : v);
            case 0x0204:
                return (new @{{long}}(@{{x}}['__v']))['__mod'](@{{y}});
            case 0x0402:
                return @{{x}}['__mod'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__mod'](@{{y}});
        }
        if (typeof @{{x}} == 'string') {
            return @{{sprintf}}(@{{x}}, @{{y}});
        }
        if (!@{{x}}['__number__']) {
            if (   !@{{y}}['__number__']
                && @{{x}}['__mro__']['length'] > @{{y}}['__mro__']['length']
                && @{{isinstance}}(@{{x}}, @{{y}})
                && typeof @{{x}}['__mod__'] == 'function')
                return @{{y}}['__mod__'](@{{x}});
            if (typeof @{{x}}['__mod__'] == 'function') return @{{x}}['__mod__'](@{{y}});
        }
        if (!@{{y}}['__number__'] && typeof @{{y}}['__rmod__'] == 'function') return @{{y}}['__rmod__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for %: '%r', '%r'" % (x, y))

def op_pow(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0101:
            case 0x0104:
            case 0x0401:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return Math['pow'](@{{x}}, @{{y}});
            case 0x0102:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return Math['pow'](@{{x}},@{{y}}['__v']);
            case 0x0201:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                return Math['pow'](@{{x}}['__v'],@{{y}});
            case 0x0202:
                return @{{x}}['__pow__'](@{{y}});
            case 0x0204:
                return (new @{{long}}(@{{x}}['__v']))['__pow'](@{{y}});
            case 0x0402:
                return @{{x}}['__pow'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__pow'](@{{y}});
        }
        if (!@{{x}}['__number__']) {
            if (   !@{{y}}['__number__']
                && @{{x}}['__mro__']['length'] > @{{y}}['__mro__']['length']
                && @{{isinstance}}(@{{x}}, @{{y}})
                && typeof @{{x}}['__pow__'] == 'function')
                return @{{y}}['__pow__'](@{{x}});
            if (typeof @{{x}}['__pow__'] == 'function') return @{{x}}['__pow__'](@{{y}});
        }
        if (!@{{y}}['__number__'] && typeof @{{y}}['__rpow__'] == 'function') return @{{y}}['__rpow__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for %: '%r', '%r'" % (x, y))

def op_invert(v):
    JS("""
    if (@{{v}} !== null) {
        if (typeof @{{v}}['__invert__'] == 'function') return @{{v}}['__invert__']();
    }
""")
    raise TypeError("bad operand type for unary -: '%r'" % v)

def op_bitshiftleft(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0202:
                return @{{x}}['__lshift__'](@{{y}});
            case 0x0204:
                return @{{y}}['__rlshift__'](@{{x}});
            case 0x0402:
                return @{{x}}['__lshift'](@{{y}}['__v']);
            case 0x0404:
                return @{{x}}['__lshift'](@{{y}}['valueOf']());
        }
        if (typeof @{{x}}['__lshift__'] == 'function') {
            var v = @{{x}}['__lshift__'](@{{y}});
            if (v !== @{{NotImplemented}}) return v;
        }
        if (typeof @{{y}}['__rlshift__'] != 'undefined') return @{{y}}['__rlshift__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for <<: '%r', '%r'" % (x, y))

def op_bitshiftright(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0202:
                return @{{x}}['__rshift__'](@{{y}});
            case 0x0204:
                return @{{y}}['__rrshift__'](@{{x}});
            case 0x0402:
                return @{{x}}['__rshift'](@{{y}}['__v']);
            case 0x0404:
                return @{{x}}['__rshift'](@{{y}}['valueOf']());
        }
        if (typeof @{{x}}['__rshift__'] == 'function') {
            var v = @{{x}}['__rshift__'](@{{y}});
            if (v !== @{{NotImplemented}}) return v;
        }
        if (typeof @{{y}}['__rrshift__'] != 'undefined') return @{{y}}['__rrshift__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for >>: '%r', '%r'" % (x, y))

def op_bitand2(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0202:
                return @{{x}}['__and__'](@{{y}});
            case 0x0204:
                return @{{y}}['__and'](new @{{long}}(@{{x}}));
            case 0x0402:
                return @{{x}}['__and'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__and'](@{{y}});
        }
        if (typeof @{{x}}['__and__'] == 'function') {
            var v = @{{x}}['__and__'](@{{y}});
            if (v !== @{{NotImplemented}}) return v;
        }
        if (typeof @{{y}}['__rand__'] != 'undefined') return @{{y}}['__rand__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for &: '%r', '%r'" % (x, y))

op_bitand = JS("""function (args) {
    var a;
    if (args[0] !== null && args[1] !== null && args['length'] > 1) {
        var res, r;
        res = args[0];
        for (i = 1; i < args['length']; i++) {
            if (typeof res['__and__'] == 'function') {
                r = res;
                res = res['__and__'](args[i]);
                if (res === @{{NotImplemented}} && typeof args[i]['__rand__'] == 'function') {
                    res = args[i]['__rand__'](r);
                }
            } else if (typeof args[i]['__rand__'] == 'function') {
                res = args[i]['__rand__'](res);
            } else {
                res = null;
                break;
            }
            if (res === @{{NotImplemented}}) {
                res = null;
                break;
            }
        }
        if (res !== null) {
            return res;
        }
    }
""")
raise TypeError("unsupported operand type(s) for &: " + ', '.join([repr(a) for a in list(args)]))
JS("""
};
""")

def op_bitxor2(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0202:
                return @{{x}}['__xor__'](@{{y}});
            case 0x0204:
                return @{{y}}['__xor'](new @{{long}}(@{{x}}));
            case 0x0402:
                return @{{x}}['__xor'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__xor'](@{{y}});
        }
        if (typeof @{{x}}['__xor__'] == 'function') {
            var v = @{{x}}['__xor__'](@{{y}});
            if (v !== @{{NotImplemented}}) return v;
        }
        if (typeof @{{y}}['__rxor__'] != 'undefined') return @{{y}}['__rxor__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for ^: '%r', '%r'" % (x, y))

op_bitxor = JS("""function (args) {
    var a;
    if (args[0] !== null && args[1] !== null && args['length'] > 1) {
        var res, r;
        res = args[0];
        for (i = 1; i < args['length']; i++) {
            if (typeof res['__xor__'] == 'function') {
                r = res;
                res = res['__xor__'](args[i]);
                if (res === @{{NotImplemented}} && typeof args[i]['__rxor__'] == 'function') {
                    res = args[i]['__rxor__'](r);
                }
            } else if (typeof args[i]['__rxor__'] == 'function') {
                res = args[i]['__rxor__'](res);
            } else {
                res = null;
                break;
            }
            if (res === @{{NotImplemented}}) {
                res = null;
                break;
            }
        }
        if (res !== null) {
            return res;
        }
    }
""")
raise TypeError("unsupported operand type(s) for ^: " + ', '.join([repr(a) for a in args]))
JS("""
};
""")

def op_bitor2(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0202:
                return @{{x}}['__or__'](@{{y}});
            case 0x0204:
                return @{{y}}['__or'](new @{{long}}(@{{x}}));
            case 0x0402:
                return @{{x}}['__or'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__or'](@{{y}});
        }
        if (typeof @{{x}}['__or__'] == 'function') {
            var v = @{{x}}['__or__'](@{{y}});
            if (v !== @{{NotImplemented}}) return v;
        }
        if (typeof @{{y}}['__ror__'] != 'undefined') {
            return @{{y}}['__ror__'](@{{x}});
        }
    }
""")
    raise TypeError("unsupported operand type(s) for |: '%r', '%r'" % (x, y))

op_bitor = JS("""function (args) {
    var a;
    if (args[0] !== null && args[1] !== null && args['length'] > 1) {
        var res, r;
        res = args[0];
        for (i = 1; i < args['length']; i++) {
            if (typeof res['__or__'] == 'function') {
                r = res;
                res = res['__or__'](args[i]);
                if (res === @{{NotImplemented}} && typeof args[i]['__ror__'] == 'function') {
                    res = args[i]['__ror__'](r);
                }
            } else if (typeof args[i]['__ror__'] == 'function') {
                res = args[i]['__ror__'](res);
            } else {
                res = null;
                break;
            }
            if (res === @{{NotImplemented}}) {
                res = null;
                break;
            }
        }
        if (res !== null) {
            return res;
        }
    }
""")
raise TypeError("unsupported operand type(s) for |: " + ', '.join([repr(a) for a in args]))
JS("""
};
""")


# All modules (do and should) take care of checking their parent:
#   - If the parent is not loaded and initialized, call ___import___(parent, null)
# All modules are placed in sys.modules dict
# The module is first tried within the context
# If the depth > 1 (i.e. one or more dots in the path) then:
#     Try the parent if it has an object that resolves to [context.]path
# If the module doesn't exist and dynamic loading is enabled, try dynamic loading
def ___import___(path, context, module_name=None, get_base=True):
    save_track_module = JS("$pyjs['track']['module']")
    sys = JS("$pyjs['loaded_modules']['sys']")
    pyjslib = JS("$pyjs['loaded_modules']['pyjslib']")
    if JS("@{{sys}}['__was_initialized__'] != true"):
        module = JS("$pyjs['loaded_modules'][@{{path}}]")
        module()
        JS("$pyjs['track']['module'] = @{{save_track_module}};")
        if path == 'sys':
            module.modules = dict({'pyjslib': pyjslib,
                                   '__builtin__':pyjslib,
                                   'builtins':pyjslib,
                                   'sys': module})
            JS("$pyjs['loaded_modules']['__builtin__'] = @{{pyjslib}};")
            JS("$pyjs['loaded_modules']['builtins'] = @{{pyjslib}};")
        return module
    importName = path
    is_module_object = False
    path_parts = path.__split('.') # make a javascript Array
    depth = path_parts.length
    topName = JS("@{{path_parts}}[0]")
    objName = JS("@{{path_parts}}[@{{path_parts}}['length']-1]")
    parentName = path_parts.slice(0, path_parts.length-1).join('.')
    if context is None:
        in_context = False
    else:
        in_context = True
        inContextImportName = context + '.' + importName
        if not parentName:
            inContextParentName = context
        else:
            inContextParentName = context + '.' + parentName
        inContextTopName = context + '.' + topName
        contextTopName = JS("@{{context}}['__split']('.')[0]")

        # Check if we already have imported this module in this context
        if depth > 1 and sys.modules.has_key(inContextParentName):
            module = sys.modules[inContextParentName]
            if JS("typeof @{{module}}[@{{objName}}] != 'undefined'"):
                if get_base:
                    return JS("$pyjs['loaded_modules'][@{{inContextTopName}}]")
                return JS("@{{module}}[@{{objName}}]")
        elif sys.modules.has_key(inContextImportName):
            if get_base:
                return JS("$pyjs['loaded_modules'][@{{inContextTopName}}]")
            return sys.modules[inContextImportName]
        elif depth > 1 and JS("typeof (@{{module}} = $pyjs['loaded_modules'][@{{inContextParentName}}]) != 'undefined'"):
            sys.modules[inContextParentName] = module
            JS("@{{module}}['__was_initialized__'] = false;")
            module(None)
            JS("$pyjs['track']['module'] = @{{save_track_module}};")
            if JS("typeof @{{module}}[@{{objName}}] != 'undefined'"):
                if get_base:
                    return JS("$pyjs['loaded_modules'][@{{inContextTopName}}]")
                return JS("@{{module}}[@{{objName}}]")
        if sys.modules.has_key(inContextImportName):
            if get_base:
                return JS("$pyjs['loaded_modules'][@{{inContextTopName}}]")
            return sys.modules[inContextImportName]
        if JS("typeof (@{{module}} = $pyjs['loaded_modules'][@{{inContextImportName}}]) != 'undefined'"):
            sys.modules[inContextImportName] = module
            JS("@{{module}}['__was_initialized__'] = false;")
            module(module_name)
            JS("$pyjs['track']['module'] = @{{save_track_module}};")
            if get_base:
                return JS("$pyjs['loaded_modules'][@{{inContextTopName}}]")
            return module
        # Check if the topName is a valid module, if so, we stay in_context
        if not sys.modules.has_key(inContextTopName):
            if JS("typeof (@{{module}} = $pyjs['loaded_modules'][@{{inContextTopName}}]) != 'function'"):
                in_context = False
                if JS("$pyjs['options']['dynamic_loading']"):
                    module = __dynamic_load__(inContextTopName)
                    if JS("""typeof @{{module}} == 'function'"""):
                        in_context = True
                        if depth == 1:
                            module(module_name)
                            JS("$pyjs['track']['module'] = @{{save_track_module}};")
                            return module
                        else:
                            module(None)
                            if depth == 2 and JS("typeof @{{module}}[@{{objName}}] != 'undefined'"):
                                if get_base:
                                    return JS("$pyjs['loaded_modules'][@{{inContextTopName}}]")
                                return JS("@{{module}}[@{{objName}}]")
        if in_context:
            importName = inContextImportName
            parentName = inContextParentName
            topName = inContextTopName
    if not in_context:
        if parentName and sys.modules.has_key(parentName):
            module = sys.modules[parentName]
            if JS("typeof @{{module}}[@{{objName}}] != 'undefined'"):
                if get_base:
                    return JS("$pyjs['loaded_modules'][@{{topName}}]")
                return JS("@{{module}}[@{{objName}}]")
        elif sys.modules.has_key(importName):
            if get_base:
                return JS("$pyjs['loaded_modules'][@{{topName}}]")
            return sys.modules[importName]
        elif parentName and JS("typeof (@{{module}} = $pyjs['loaded_modules'][@{{parentName}}]) != 'undefined'"):
            sys.modules[parentName] = module
            JS("@{{module}}['__was_initialized__'] = false;")
            module(None)
            JS("$pyjs['track']['module'] = @{{save_track_module}};")
            if JS("typeof @{{module}}[@{{objName}}] != 'undefined'"):
                if get_base:
                    return JS("$pyjs['loaded_modules'][@{{topName}}]")
                return JS("@{{module}}[@{{objName}}]")
        if sys.modules.has_key(importName):
            if get_base:
                return JS("$pyjs['loaded_modules'][@{{topName}}]")
            return sys.modules[importName]
        if JS("typeof (@{{module}} = $pyjs['loaded_modules'][@{{importName}}]) != 'undefined'"):
            sys.modules[importName] = module
            if importName != 'pyjslib' and importName != 'sys':
                JS("@{{module}}['__was_initialized__'] = false;")
            module(module_name)
            JS("$pyjs['track']['module'] = @{{save_track_module}};")
            if get_base:
                return JS("$pyjs['loaded_modules'][@{{topName}}]")
            return module

    # If we are here, the module is not loaded (yet).
    if JS("$pyjs['options']['dynamic_loading']"):
        module = __dynamic_load__(importName)
        if JS("""typeof @{{module}}== 'function'"""):
            module(module_name)
            JS("$pyjs['track']['module'] = @{{save_track_module}};")
            if get_base:
                return JS("$pyjs['loaded_modules'][@{{topName}}]")
            return module

    raise ImportError(
        "No module named %s, %s in context %s" % (importName, path, context))

def __dynamic_load__(importName):
    global __nondynamic_modules__
    setCompilerOptions("noDebug")
    module = JS("""$pyjs['loaded_modules'][@{{importName}}]""")
    if sys is None or dynamic is None or __nondynamic_modules__.has_key(importName):
        return module
    if JS("""typeof @{{module}}== 'undefined'"""):
        try:
            dynamic.ajax_import("lib/" + importName + ".__" + platform + "__.js")
            module = JS("""$pyjs['loaded_modules'][@{{importName}}]""")
        except:
            pass
    if JS("""typeof @{{module}}== 'undefined'"""):
        try:
            dynamic.ajax_import("lib/" + importName + ".js")
            module = JS("""$pyjs['loaded_modules'][@{{importName}}]""")
        except:
            pass
        if JS("""typeof @{{module}}== 'undefined'"""):
            __nondynamic_modules__[importName] = 1.0
    return module

def __import_all__(path, context, namespace, module_name=None, get_base=True):
    module = ___import___(path, context, module_name, get_base)
    if JS("""typeof @{{module}}['__all__'] == 'undefined'"""):
        for name in dir(module):
            if not name.startswith('_'):
                JS("""@{{namespace}}[@{{name}}] = @{{module}}[@{{name}}];""")
    else:
        for name in module.__all__:
            JS("""@{{namespace}}[@{{name}}] = @{{module}}[@{{name}}];""")

class BaseException:

    def __init__(self, *args):
        self.args = args

    def __getitem__(self, index):
        return self.args.__getitem__(index)

    def toString(self):
        return self.__name__ + ': ' + self.__str__()

    def __str__(self):
        if len(self.args) is 0:
            return ''
        elif len(self.args) is 1:
            return str(self.args[0])
        return repr(self.args)

    def __repr__(self):
        if callable(self):
            return "<type '%s'>" % self.__name__
        return self.__name__ + repr(self.args)

class KeyboardInterrupt(BaseException):
    pass

class GeneratorExit(BaseException):
    pass

class SystemExit(BaseException):
    pass


class Exception(BaseException):
    pass

class StandardError(Exception):
    pass

class ArithmeticError(StandardError):
    pass

class StopIteration(Exception):
    pass

class GeneratorExit(Exception):
    pass

class AssertionError(StandardError):
    pass

class TypeError(StandardError):
    pass

class AttributeError(StandardError):
    pass

class NameError(StandardError):
    pass

class ValueError(StandardError):
    pass

class ImportError(StandardError):
    pass

class LookupError(StandardError):
    pass

class RuntimeError(StandardError):
    pass

class SystemError(StandardError):
    pass

class KeyError(LookupError):

    def __str__(self):
        if len(self.args) is 0:
            return ''
        elif len(self.args) is 1:
            return repr(self.args[0])
        return repr(self.args)

class IndexError(LookupError):
    pass

class NotImplementedError(RuntimeError):
    pass

class ZeroDivisionError(ArithmeticError):
    pass

class OverflowError(ArithmeticError):
    pass

class UndefinedValueError(ValueError):
    pass

def init():

    # There seems to be an bug in Chrome with accessing the message
    # property, on which an error is thrown
    # Hence the declaration of 'var message' and the wrapping in try..catch
    JS("""
@{{_errorMapping}} = function(err) {
    if (err instanceof(ReferenceError) || err instanceof(TypeError)) {
        var message = '';
        try {
            message = err['message'];
        } catch ( e) {
        }
        return @{{AttributeError}}(message);
    }
    return err;
};
""")
    # The TryElse 'error' is used to implement the else in try-except-else
    # (to raise an exception when there wasn't any)
    JS("""
@{{TryElse}} = function () { };
@{{TryElse}}['prototype'] = new Error();
@{{TryElse}}['__name__'] = 'TryElse';
""")

    # Patching of the standard javascript String object
    JS("""
String['prototype']['rfind'] = function(sub, start, end) {
    var pos;
    if (typeof start != 'undefined') {
        /* *sigh* - python rfind goes *RIGHT*, NOT left */
        pos = this['substring'](start)['lastIndexOf'](sub);
        if (pos == -1) {
            return -1;
        }
        pos += start;
    }
    else {
        pos=this['lastIndexOf'](sub, start);
    }
    if (typeof end == 'undefined') return pos;

    if (pos + sub['length']>end) return -1;
    return pos;
};

String['prototype']['find'] = function(sub, start, end) {
    var pos=this['indexOf'](sub, start);
    if (typeof end == 'undefined') return pos;

    if (pos + sub['length']>end) return -1;
    return pos;
};
String['prototype']['index'] = function(sub, start, end) {
    var pos = this['find'](sub, start, end);
    if (pos < 0)
        throw @{{ValueError}}('substring not found');
    return pos;
}
String['prototype']['count'] = function(sub, start, end) {
    var pos, count = 0, n = sub['length'];
    if (typeof start == 'undefined') start = 0;
    if (typeof end == 'undefined') end = this['length'];
    while (start < end) {
        pos = this['find'](sub, start, end);
        if (pos < 0) break;
        count ++;
        start = pos + n;
    }
    return count;
}

String['prototype']['format'] = function() {
    var args = $p['tuple']($pyjs_array_slice['call'](arguments,0,arguments['length']-1));

    var kw = arguments['length'] >= 1 ? arguments[arguments['length']-1] : arguments[arguments['length']];
    if (typeof kw != 'object' || kw['__name__'] != 'dict' || typeof kw['$pyjs_is_kwarg'] == 'undefined') {
        if (typeof kw != 'undefined') args['__array']['push'](kw);
        kw = arguments[arguments['length']+1];
    } else {
        delete kw['$pyjs_is_kwarg'];
    }
    if (typeof kw == 'undefined') {
        kw = $p['__empty_dict']();
    }
    return $p['_string_format'](this, args, kw);
}
String['prototype']['format']['__args__'] = ['args', ['kw']];

String['prototype']['join'] = function(data) {
    var text="";

    if (data['constructor'] === Array) {
        return data['join'](this);
    } else if (typeof data['__iter__'] == 'function') {
        if (typeof data['__array'] == 'object') {
            return data['__array']['join'](this);
        }
        var iter=data['__iter__']();
        if (typeof iter['__array'] == 'object') {
            return iter['__array']['join'](this);
        }
        data = [];
        var item, i = 0;
        if (typeof iter['$genfunc'] == 'function') {
            while (typeof (item=iter['next'](true)) != 'undefined') {
                data[i++] = item;
            }
        } else {
            try {
                while (true) {
                    data[i++] = iter['next']();
                }
            }
            catch (e) {
                if (!@{{isinstance}}(e, @{{StopIteration}})) throw e;
            }
        }
        return data['join'](this);
    }

    return text;
};

String['prototype']['isdigit'] = function() {
    return (this['match'](/^\d+$/g) !== null);
};

String['prototype']['isalnum'] = function() {
    return (this['match'](/^[a-zA-Z\d]+$/g) !== null);
};

String['prototype']['isalpha'] = function() {
    return (this['match'](/^[a-zA-Z]+$/g) !== null);
};

String['prototype']['isupper'] = function() {
    return (this['match'](/[a-z]/g) === null);
};

String['prototype']['islower'] = function() {
    return (this['match'](/[A-Z]/g) === null);
};

String['prototype']['__replace']=String['prototype']['replace'];

String['prototype']['$$replace'] = function(old, replace, count) {
    var do_max=false;
    var start=0;
    var new_str="";
    var pos=0;

    if (typeof old != 'string') return this['__replace'](old, replace);
    if (typeof count != 'undefined') do_max=true;

    while (start<this['length']) {
        if (do_max && !count--) break;

        pos=this['indexOf'](old, start);
        if (pos<0) break;

        new_str+=this['substring'](start, pos) + replace;
        start=pos+old['length'];
    }
    if (start<this['length']) new_str+=this['substring'](start);

    return new_str;
};

String['prototype']['__contains__'] = function(s){
    return this['indexOf'](s)>=0;
};

String['prototype']['__split'] = String['prototype']['split'];

String['prototype']['$$split'] = function(sep, maxsplit) {
    var items=@{{list}}();
    var do_max=false;
    var subject=this;
    var start=0;
    var pos=0;

    if (sep === null || typeof sep == 'undefined') {
        sep=" ";
        if (subject['length'] == 0) {
            return items;
        }
        subject=subject['strip']();
        subject=subject['$$replace'](/\s+/g, sep);
    }
    else if (typeof maxsplit != 'undefined') do_max=true;

    if (subject['length'] == 0) {
        items['__array']['push']('');
        return items;
    }

    while (start<subject['length']) {
        if (do_max && !maxsplit--) break;

        pos=subject['indexOf'](sep, start);
        if (pos<0) break;

        items['__array']['push'](subject['substring'](start, pos));
        start=pos+sep['length'];
    }
    if (start<=subject['length']) items['__array']['push'](subject['substring'](start));

    return items;
};

String['prototype']['rsplit'] = function(sep, maxsplit) {
    var items=@{{list}}();
    var do_max=false;
    var subject=this;
    var pos=0;

    if (sep === null || typeof sep == 'undefined') {
        sep=" ";
        if (subject['length'] == 0) {
            return items;
        }
        subject=subject['strip']();
        subject=subject['$$replace'](/\s+/g, sep);
    }
    else if (typeof maxsplit != 'undefined') do_max=true;

    if (subject['length'] == 0) {
        items['__array']['push']('');
        return items;
    }

    while (subject['length'] > 0) {
        if (do_max && !maxsplit--) break;

        pos=subject['lastIndexOf'](sep);
        if (pos<0) break;

        items['__array']['push'](subject['substr'](pos+sep['lenght']));
        subject = subject['substr'](0, pos);
    }
    if (subject['length'] > 0) items['__array']['push'](subject);
    items['__array']['reverse']()

    return items;
};
String['prototype']['splitlines'] = function(keepends) {
    var items = this['$$split']("\\n");
    if (typeof keepends != 'undefined' && keepends)
    {
        for (var i=0; i<items['__array']['length']; i++)
        {
            items['__array'][i] = items['__array'][i] + "\\n";
        }
    }
    return items;
}
if (typeof "a"[0] == 'undefined' ) {
    // IE: cannot do "abc"[idx]
    String['prototype']['__iter__'] = function() {
        var i = 0;
        var s = this;
        return {
            'next': function(noStop) {
                if (i >= s['length']) {
                    if (noStop === true) {
                        return;
                    }
                    throw @{{StopIteration}}();
                }
                return s['charAt'](i++);
            },
            '__iter__': function() {
                return this;
            }
        };
    };
} else {
    String['prototype']['__iter__'] = function() {
        var i = 0;
        var s = this;
        return {
            '__array': this,
            'next': function(noStop) {
                if (i >= s['length']) {
                    if (noStop === true) {
                        return;
                    }
                    throw @{{StopIteration}}();
                }
                return s['charAt'](i++);
            },
            '__iter__': function() {
                return this;
            }
        };
    };
}

String['prototype']['strip'] = function(chars) {
    return this['lstrip'](chars)['rstrip'](chars);
};

String['prototype']['lstrip'] = function(chars) {
    if (typeof chars == 'undefined') return this['$$replace'](/^\s+/, "");
    if (chars['length'] == 0) return this;
    return this['$$replace'](new RegExp("^[" + chars + "]+"), "");
};

String['prototype']['rstrip'] = function(chars) {
    if (typeof chars == 'undefined') return this['$$replace'](/\s+$/, "");
    if (chars['length'] == 0) return this;
    return this['$$replace'](new RegExp("[" + chars + "]+$"), "");
};

String['prototype']['startswith'] = function(prefix, start, end) {
    // FIXME: accept tuples as suffix (since 2['5'])
    if (typeof start == 'undefined') start = 0;
    if (typeof end == 'undefined') end = this['length'];

    if ((end - start) < prefix['length']) return false;
    if (this['substr'](start, prefix['length']) == prefix) return true;
    return false;
};

String['prototype']['endswith'] = function(suffix, start, end) {
    // FIXME: accept tuples as suffix (since 2['5'])
    if (typeof start == 'undefined') start = 0;
    if (typeof end == 'undefined') end = this['length'];

    if ((end - start) < suffix['length']) return false;
    if (this['substr'](end - suffix['length'], suffix['length']) == suffix) return true;
    return false;
};

String['prototype']['ljust'] = function(width, fillchar) {
    switch (width['__number__']) {
        case 0x02:
        case 0x04:
            width = width['valueOf']();
            break;
        case 0x01:
            if (Math['floor'](width) == width) break;
        default:
            throw @{{TypeError}}("an integer is required (got '" + width + "')");
    }
    if (typeof fillchar == 'undefined') fillchar = ' ';
    if (typeof(fillchar) != 'string' ||
        fillchar['length'] != 1) {
        throw @{{TypeError}}("ljust() argument 2 must be char, not " + typeof(fillchar));
    }
    if (this['length'] >= width) return this;
    return this + new Array(width+1 - this['length'])['join'](fillchar);
};

String['prototype']['rjust'] = function(width, fillchar) {
    switch (width['__number__']) {
        case 0x02:
        case 0x04:
            width = width['valueOf']();
            break;
        case 0x01:
            if (Math['floor'](width) == width) break;
        default:
            throw @{{TypeError}}("an integer is required (got '" + width + "')");
    }
    if (typeof fillchar == 'undefined') fillchar = ' ';
    if (typeof(fillchar) != 'string' ||
        fillchar['length'] != 1) {
        throw @{{TypeError}}("rjust() argument 2 must be char, not " + typeof(fillchar));
    }
    if (this['length'] >= width) return this;
    return new Array(width + 1 - this['length'])['join'](fillchar) + this;
};

String['prototype']['center'] = function(width, fillchar) {
    switch (width['__number__']) {
        case 0x02:
        case 0x04:
            width = width['valueOf']();
            break;
        case 0x01:
            if (Math['floor'](width) == width) break;
        default:
            throw @{{TypeError}}("an integer is required (got '" + width + "')");
    }
    if (typeof fillchar == 'undefined') fillchar = ' ';
    if (typeof(fillchar) != 'string' ||
        fillchar['length'] != 1) {
        throw @{{TypeError}}("center() argument 2 must be char, not " + typeof(fillchar));
    }
    if (this['length'] >= width) return this;
    var padlen = width - this['length'];
    var right = Math['ceil'](padlen / 2);
    var left = padlen - right;
    return new Array(left+1)['join'](fillchar) + this + new Array(right+1)['join'](fillchar);
};

String['prototype']['__getslice__'] = function(lower, upper) {
    if (lower === null) {
        lower = 0;
    } else if (lower < 0) {
        lower = this['length'] + lower;
    }
    if (upper === null) {
        upper=this['length'];
    } else if (upper < 0) {
       upper = this['length'] + upper;
    }
    return this['substring'](lower, upper);
};

String['prototype']['__getitem__'] = function(idx) {
    if (idx < 0) idx += this['length'];
    if (idx < 0 || idx > this['length']) {
        throw @{{IndexError}}("string index out of range");
    }
    return this['charAt'](idx);
};

String['prototype']['__setitem__'] = function(idx, val) {
    throw @{{TypeError}}("'str' object does not support item assignment");
};

String['prototype']['upper'] = String['prototype']['toUpperCase'];
String['prototype']['lower'] = String['prototype']['toLowerCase'];

String['prototype']['capitalize'] = function() {
    return this['charAt'](0)['toUpperCase']() + this['substring'](1);
};

String['prototype']['zfill'] = function(width) {
    return this['rjust'](width, '0');
};

String['prototype']['__add__'] = function(y) {
    if (typeof y != "string") {
        throw @{{TypeError}}("cannot concatenate 'str' and non-str objects");
    }
    return this + y;
};

String['prototype']['__mul__'] = function(y) {
    switch (y['__number__']) {
        case 0x02:
        case 0x04:
            y = y['valueOf']();
            break;
        case 0x01:
            if (Math['floor'](y) == y) break;
        default:
            throw @{{TypeError}}("can't multiply sequence by non-int of type 'str'");
    }
    var s = '';
    while (y-- > 0) {
        s += this;
    }
    return s;
};
String['prototype']['__rmul__'] = String['prototype']['__mul__'];
String['prototype']['__number__'] = null;
String['prototype']['__name__'] = 'str';
String['prototype']['__class__'] = String['prototype'];
String['prototype']['__is_instance__'] = null;
String['prototype']['__str__'] = function () {
    if (typeof this == 'function') return "<type '" + this['__name__'] + "'>";
    return this['toString']();
};
String['prototype']['__repr__'] = function () {
    if (typeof this == 'function') return "<type '" + this['__name__'] + "'>";
    return "'" + this['toString']() + "'";
};
String['prototype']['__mro__'] = [@{{basestring}}];
""")

    # Patching of the standard javascript Boolean object
    JS("""
Boolean['prototype']['__number__'] = 0x01;
Boolean['prototype']['__name__'] = 'bool';
Boolean['prototype']['__class__'] = Boolean['prototype'];
Boolean['prototype']['__is_instance__'] = null;
Boolean['prototype']['__str__']= function () {
    if (typeof this == 'function') return "<type '" + this['__name__'] + "'>";
    if (this == true) return "True";
    return "False";
};
Boolean['prototype']['__repr__'] = Boolean['prototype']['__str__'];
Boolean['prototype']['__and__'] = function (y) {
    return this & y['valueOf']();
};
Boolean['prototype']['__or__'] = function (y) {
    return this | y['valueOf']();
};
Boolean['prototype']['__xor__'] = function (y) {
    return this ^ y['valueOf']();
};
""")

    # Patching of the standard javascript Array object
    # This makes it imposible to use for (k in Array())
    JS("""
if (typeof Array['prototype']['indexOf'] != 'function') {
    Array['prototype']['indexOf'] = function(elt /*, from*/) {
        var len = this['length'] >>> 0;

        var from = Number(arguments[1]) || 0;
        from = (from < 0)
                ? Math['ceil'](from)
                : Math['floor'](from);
        if (from < 0)
            from += len;

        for (; from < len; from++) {
            if (from in this &&
                this[from] === elt)
                return from;
        }
        return -1;
    };
};
""")

    # Patching of the standard javascript RegExp
    JS("""
RegExp['prototype']['Exec'] = function(pat) {
    var m = this['exec'](pat);
    if (m !== null) {
        var len = m['length'] >>> 0;
        for (var i = 0; i < len; i++) {
            if (typeof(m[i]) == 'undefined')
                m[i] = null;
        }
    }
    return m;
};
""")
    JS("""
@{{abs}} = Math['abs'];
""")

class Class:
    def __init__(self, name):
        self.name = name

    def __str___(self):
        return self.name

def open(fname, mode='r'):
    raise NotImplementedError("open is not implemented in browsers")

cmp = JS("""function(a, b) {
    if (typeof a == typeof b) {
        switch (typeof a) {
            case 'number':
            case 'string':
            case 'boolean':
                return a == b ? 0 : (a < b ? -1 : 1);
        }
        if (a === b) return 0;
    }
    if (a === null) {
        if (b === null) return 0;
        return -1;
    }
    if (b === null) {
        return 1;
    }

    switch ((a['__number__'] << 8)|b['__number__']) {
        case 0x0202:
            a = a['__v'];
            b = b['__v'];
        case 0x0101:
            return a == b ? 0 : (a < b ? -1 : 1);
        case 0x0100:
        case 0x0200:
        case 0x0400:
            if (typeof b['__cmp__'] == 'function') {
                return -b['__cmp__'](a);
            }
            return -1;
        case 0x0001:
        case 0x0002:
        case 0x0004:
            if (typeof a['__cmp__'] == 'function') {
                return a['__cmp__'](b);
            }
            return 1;
        case 0x0102:
            return -b['__cmp__'](new @{{int}}(a));
        case 0x0104:
            return -b['__cmp__'](new @{{long}}(a));
        case 0x0201:
            return a['__cmp__'](new @{{int}}(b));
        case 0x0401:
            return a['__cmp__'](new @{{long}}(b));
        case 0x0204:
            return -b['__cmp__'](new @{{long}}(a));
        case 0x0402:
            return a['__cmp__'](new @{{long}}(b));
        case 0x0404:
            return a['__cmp__'](b);
    }

    if (typeof a['__class__'] == typeof b['__class__'] && typeof a['__class__'] == 'function') {
        if (a['__class__']['__name__'] < b['__class__']['__name__']) {
            return -1;
        }
        if (a['__class__']['__name__'] > b['__class__']['__name__']) {
            return 1;
        }
    }

    if ((typeof a == 'object' || typeof a == 'function') && typeof a['__cmp__'] == 'function') {
        return a['__cmp__'](b);
    } else if ((typeof b == 'object' || typeof b == 'function') && typeof b['__cmp__'] == 'function') {
        return -b['__cmp__'](a);
    }
    if (a == b) return 0;
    if (a > b) return 1;
    return -1;
};
    """)

# for list.sort()
__cmp = cmp

def bool(v):
    # this needs to stay in native code without any dependencies here,
    # because this is used by if and while, we need to prevent
    # recursion
    #setCompilerOptions("InlineBool")
    #if v:
    #    return True
    #return False
    JS("""
    switch (@{{v}}) {
        case null:
        case false:
        case 0:
        case '':
            return false;
    }
    if (typeof @{{v}} == 'object') {
        if (typeof @{{v}}['__nonzero__'] == 'function'){
            return @{{v}}['__nonzero__']();
        } else if (typeof @{{v}}['__len__'] == 'function'){
            return @{{v}}['__len__']() > 0;
        }
    }
    return true;
    """)

class float:
    __number__ = JS("0x01")
    def __new__(self, num):
        JS("""
        if (typeof @{{num}} == 'string') {
            @{{num}} = @{{num}}['lstrip']();
            if (@{{num}} === "") {
                throw @{{ValueError}}("empty string for float()");
            }
        }
        var v = Number(@{{num}});
        if (isNaN(v)) {
            throw @{{ValueError}}("invalid literal for float(): " + @{{!num}});
        }
        return v;
""")
# Patching of the standard javascript Number
# which is in principle the python 'float'
JS("""
Number['prototype']['__number__'] = 0x01;
Number['prototype']['__name__'] = 'float';
Number['prototype']['__init__'] = function (value, radix) {
    return null;
};

Number['prototype']['__str__'] = function () {
    if (typeof this == 'function') return "<type '" + this['__name__'] + "'>";
    return this['toString']();
};

Number['prototype']['__repr__'] = function () {
    if (typeof this == 'function') return "<type '" + this['__name__'] + "'>";
    return this['toString']();
};

Number['prototype']['__nonzero__'] = function () {
    return this != 0;
};

Number['prototype']['__cmp__'] = function (y) {
    return this < y? -1 : (this == y ? 0 : 1);
};

Number['prototype']['__hash__'] = function () {
    return this;
};

Number['prototype']['__oct__'] = function () {
    return '0'+this['toString'](8);
};

Number['prototype']['__hex__'] = function () {
    return '0x'+this['toString'](16);
};

Number['prototype']['__pos__'] = function () {
    return this;
};

Number['prototype']['__neg__'] = function () {
    return -this;
};

Number['prototype']['__abs__'] = function () {
    if (this >= 0) return this;
    return -this;
};

Number['prototype']['__add__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    return this + y;
};

Number['prototype']['__radd__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    return y + this;
};

Number['prototype']['__sub__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    return this - y;
};

Number['prototype']['__rsub__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    return y - this;
};

Number['prototype']['__floordiv__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    if (y == 0) throw @{{ZeroDivisionError}}('float divmod()');
    return Math['floor'](this / y);
};

Number['prototype']['__rfloordiv__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    if (this == 0) throw @{{ZeroDivisionError}}('float divmod');
    return Math['floor'](y / this);
};

Number['prototype']['__div__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    if (y == 0) throw @{{ZeroDivisionError}}('float division');
    return this / y;
};

Number['prototype']['__rdiv__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    if (this == 0) throw @{{ZeroDivisionError}}('float division');
    return y / this;
};

Number['prototype']['__mul__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    return this * y;
};

Number['prototype']['__rmul__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    return y * this;
};

Number['prototype']['__mod__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    if (y == 0) throw @{{ZeroDivisionError}}('float modulo');
    return this % y;
};

Number['prototype']['__rmod__'] = function (y) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    if (this == 0) throw @{{ZeroDivisionError}}('float modulo');
    return y % this;
};

Number['prototype']['__pow__'] = function (y, z) {
    if (!y['__number__'] || isNaN(y = y['valueOf']())) return @{{NotImplemented}};
    if (typeof z == 'undefined' || z == null) {
        return Math['pow'](this, y);
    }
    if (!z['__number__'] || isNaN(z = z['valueOf']())) return @{{NotImplemented}};
    return Math['pow'](this, y) % z;
};
""")

float_js = float

class float:
    def __init__(self, num):
        self.__v = float_js(num)

    def __str__(self):
        return self.__v.__str__()

    def __repr__(self):
        return self.__v.__repr__()

    def __nonzero__(self):
        return self.__v.__nonzero__()

    def __cmp__(self, other):
        return self.__v.__cmp__(other)

    def __hash__(self):
        return self.__v.__hash__()

    def __oct__(self):
        return self.__v.__oct__()

    def __hex__(self):
        return self.__v.__hex__()

    def __pos__(self):
        return self.__v.__pos__()

    def __neg__(self):
        return self.__v.__neg__()

    def __abs__(self):
        return self.__v.__abs__()

    def __add__(self, other):
        return self.__v.__add__(other)

    def __radd__(self, other):
        return self.__v.__radd__(other)

    def __sub__(self, other):
        return self.__v.__sub__(other)

    def __rsub__(self, other):
        return self.__v.__rsub__(other)

    def __floordiv__(self, other):
        return self.__v.__floordiv__(other)

    def __rfloordiv__(self, other):
        return self.__v.__rfloordiv__(other)

    def __div__(self, other):
        return self.__v.__div__(other)

    def __rdiv__(self, other):
        return self.__v.__rdiv__(other)

    def __mul__(self, other):
        return self.__v.__mul__(other)

    def __rmul__(self, other):
        return self.__v.__rmul__(other)

    def __mod__(self, other):
        return self.__v.__mod__(other)

    def __rmod__(self, other):
        return self.__v.__rmod__(other)

    def __pow__(self, y, z):
        return self.__v.__pow__(y, z)

float_py = float
float = float_js

def float_int(value, radix=None):
    JS("""
    var v;
    if (typeof @{{value}}['__int__'] != 'undefined') {
        return @{{value}}['__int__']();
    }
    if (@{{value}}['__number__']) {
        if (@{{radix}} !== null) {
            throw @{{TypeError}}("int() can't convert non-string with explicit base");
        }
        v = @{{value}}['valueOf']();
        if (v > 0) {
            v = Math['floor'](v);
        } else {
            v = Math['ceil'](v);
        }
    } else if (typeof @{{value}} == 'string') {
        if (@{{radix}} === null) {
            @{{radix}} = 10;
        }
        @{{value}} = @{{value}}['lstrip']();
        switch (@{{value}}[@{{value}}['length']-1]) {
            case 'l':
            case 'L':
                v = @{{value}}['slice'](0, @{{value}}['length']-2);
                break;
            default:
                v = @{{value}};
        }
        if (v['match']($radix_regex[@{{radix}}]) === null) {
            v = NaN;
        } else {
            v = v['$$replace'](' ', '');
            v = parseInt(v, @{{radix}});
        }
    } else {
        throw @{{TypeError}}("TypeError: int() argument must be a string or a number");
    }
    if (isNaN(v) || !isFinite(v)) {
        throw @{{ValueError}}("invalid literal for int() with base " + @{{!radix}} + ": '" + @{{!value}} + "'");
    }
    return v;
""")

JS("""
var $radix_regex = [
    /^$/i,              //  0
    /^$/i,              //  1
    /^ *-? *[01]+ *$/i,     //  2
    /^ *-? *[0-2]+ *$/i,    //  3
    /^ *-? *[0-3]+ *$/i,    //  4
    /^ *-? *[0-4]+ *$/i,    //  5
    /^ *-? *[0-5]+ *$/i,    //  6
    /^ *-? *[0-6]+ *$/i,    //  7
    /^ *-? *[0-7]+ *$/i,    //  8
    /^ *-? *[0-8]+ *$/i,    //  9
    /^ *-? *[0-9]+ *$/i,    // 10
    /^ *-? *[0-9a]+ *$/i,   // 11
    /^ *-? *[0-9ab]+ *$/i,  // 12
    /^ *-? *[0-9a-c]+ *$/i, // 13
    /^ *-? *[0-9a-d]+ *$/i, // 14
    /^ *-? *[0-9a-e]+ *$/i, // 15
    /^ *-? *[0-9a-f]+ *$/i, // 16
    /^ *-? *[0-9a-g]+ *$/i, // 17
    /^ *-? *[0-9a-h]+ *$/i, // 18
    /^ *-? *[0-9a-i]+ *$/i, // 19
    /^ *-? *[0-9a-j]+ *$/i, // 20
    /^ *-? *[0-9a-k]+ *$/i, // 21
    /^ *-? *[0-9a-l]+ *$/i, // 22
    /^ *-? *[0-9a-m]+ *$/i, // 23
    /^ *-? *[0-9a-n]+ *$/i, // 24
    /^ *-? *[0-9a-o]+ *$/i, // 25
    /^ *-? *[0-9a-p]+ *$/i, // 26
    /^ *-? *[0-9a-q]+ *$/i, // 27
    /^ *-? *[0-9a-r]+ *$/i, // 28
    /^ *-? *[0-9a-s]+ *$/i, // 29
    /^ *-? *[0-9a-t]+ *$/i, // 30
    /^ *-? *[0-9a-u]+ *$/i, // 31
    /^ *-? *[0-9a-v]+ *$/i, // 32
    /^ *-? *[0-9a-w]+ *$/i, // 33
    /^ *-? *[0-9a-x]+ *$/i, // 34
    /^ *-? *[0-9a-y]+ *$/i, // 35
    /^ *-? *[0-9a-z]+ *$/i  // 36
];

(function(){
    /* XXX do not convert to @{{int}} - this is correct */
    var $int = pyjslib['int'] = function (value, radix) {
        var v, i;
        if (typeof radix == 'undefined' || radix === null) {
            if (typeof value == 'undefined') {
                throw @{{TypeError}}("int() takes at least 1 argument");
            }
            if (typeof value['__int__'] != 'undefined') {
                return value['__int__']();
            }
            switch (value['__number__']) {
                case 0x01:
                    value = value > 0 ? Math['floor'](value) : Math['ceil'](value);
                    break;
                case 0x02:
                    return value;
                case 0x04:
                    v = value['valueOf']();
                    if (!($min_int <= v && v <= $max_int))
                        return value;
            }
            radix = null;
        }
        if (typeof this != 'object' || this['__number__'] != 0x02) return new $int(value, radix);
        if (value['__number__']) {
            if (radix !== null) throw @{{TypeError}}("int() can't convert non-string with explicit base");
            v = value['valueOf']();
        } else if (typeof value == 'string') {
            if (radix === null) {
                radix = 10;
            }
            if (value['match']($radix_regex[radix]) === null) {
                value = value['lstrip']();
                v = NaN;
            } else {
                value = value['$$replace'](' ', '');
                v = parseInt(value, radix);
            }
        } else {
            throw @{{TypeError}}("TypeError: int() argument must be a string or a number");
        }
        if (isNaN(v) || !isFinite(v)) {
            throw @{{ValueError}}("invalid literal for int() with base " + @{{!radix}} + ": '" + @{{!value}} + "'");
        }
        if ($min_int <= v && v <= $max_int) {
            this['__v'] = v;
            return this;
        }
        return new pyjslib['long'](v);
    };
    $int['__init__'] = function () {};
    $int['__number__'] = 0x02;
    $int['__v'] = 0;
    $int['__name__'] = 'int';
    $int['prototype'] = $int;
    $int['__class__'] = $int;

    $int['toExponential'] = function (fractionDigits) {
        return (typeof fractionDigits == 'undefined' || fractionDigits === null) ? this['__v']['toExponential']() : this['__v']['toExponential'](fractionDigits);
    };

    $int['toFixed'] = function (digits) {
        return (typeof digits == 'undefined' || digits === null) ? this['__v']['toFixed']() : this['__v']['toFixed'](digits);
    };

    $int['toLocaleString'] = function () {
        return this['__v']['toLocaleString']();
    };

    $int['toPrecision'] = function (precision) {
        return (typeof precision == 'undefined' || precision === null) ? this['__v']['toPrecision']() : this['__v']['toPrecision'](precision);
    };

    $int['toString'] = function (radix) {
        return (typeof radix == 'undefined' || radix === null) ? this['__v']['toString']() : this['__v']['toString'](radix);
    };

    $int['valueOf'] = function () {
        return this['__v']['valueOf']();
    };

    $int['__str__'] = function () {
        if (typeof this == 'function') return "<type '" + this['__name__'] + "'>";
        if (this['__number__'] == 0x02) return this['__v']['toString']();
        return this['toString']();
    };

    $int['__repr__'] = function () {
        if (typeof this == 'function') return "<type '" + this['__name__'] + "'>";
        if (this['__number__'] == 0x02) return this['__v']['toString']();
        return this['toString']();
    };

    $int['__nonzero__'] = function () {
        return this['__v'] != 0;
    };

    $int['__cmp__'] = function (y) {
        return this['__v'] < y? -1 : (this['__v'] == y ? 0 : 1);
    };

    $int['__hash__'] = function () {
        return this['__v'];
    };

    $int['__invert__'] = function () {
        return new $int(~this['__v']);
    };

    $int['__lshift__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        if (y < 32) {
            var v = this['__v'] << y;
            if (v > this['__v']) {
                return new $int(v);
            }
        }
        return new @{{long}}(this['__v'])['__lshift__'](y);
    };

    $int['__rlshift__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        if (this['__v'] < 32) {
            var v = y << this['__v'];
            if (v > this['__v']) {
                return new $int(v);
            }
        }
        return new @{{long}}(y)['__lshift__'](this['__v']);
    };

    $int['__rshift__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        return new $int(this['__v'] >> y);
    };

    $int['__rrshift__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        return new $int(y >> this['__v']);
    };

    $int['__and__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        return new $int(this['__v'] & y);
    };

    $int['__rand__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        return new $int(y & this['__v']);
    };

    $int['__xor__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        return new $int(this['__v'] ^ y);
    };

    $int['__rxor__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        return new $int(y ^ this['__v']);
    };

    $int['__or__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        return new $int(this['__v'] | y);
    };

    $int['__ror__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        return new $int(y | this['__v']);
    };

    $int['__oct__'] = function () {
        return '0x'+this['__v']['toString'](8);
    };

    $int['__hex__'] = function () {
        return '0x'+this['__v']['toString'](16);
    };

    $int['__pos__'] = function () {
        return this;
    };

    $int['__neg__'] = function () {
        return new $int(-this['__v']);
    };

    $int['__abs__'] = function () {
        if (this['__v'] >= 0) return this;
        return new $int(-this['__v']);
    };

    $int['__add__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        var v = this['__v'] + y;
        if ($min_int <= v && v <= $max_int) {
            return new $int(v);
        }
        if (-$max_float_int < v && v < $max_float_int) {
            return new @{{long}}(v);
        }
        return new @{{long}}(this['__v'])['__add__'](new @{{long}}(y));
    };

    $int['__radd__'] = $int['__add__'];

    $int['__sub__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        var v = this['__v'] - y;
        if ($min_int <= v && v <= $max_int) {
            return new $int(v);
        }
        if (-$max_float_int < v && v < $max_float_int) {
            return new @{{long}}(v);
        }
        return new @{{long}}(this['__v'])['__sub__'](new @{{long}}(y));
    };

    $int['__rsub__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        var v = y -this['__v'];
        if ($min_int <= v && v <= $max_int) {
            return new $int(v);
        }
        if (-$max_float_int < v && v < $max_float_int) {
            return new @{{long}}(v);
        }
        return new @{{long}}(y)['__sub__'](new @{{long}}(this['__v']));
    };

    $int['__floordiv__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        if (y == 0) throw @{{ZeroDivisionError}}('integer division or modulo by zero');
        return new $int(Math['floor'](this['__v'] / y));
    };

    $int['__rfloordiv__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        if (this['__v'] == 0) throw @{{ZeroDivisionError}}('integer division or modulo by zero');
        return new $int(Math['floor'](y / this['__v']));
    };

    $int['__div__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        if (y == 0) throw @{{ZeroDivisionError}}('integer division or modulo by zero');
        return new $int(this['__v'] / y);
    };

    $int['__rdiv__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        if (this['__v'] == 0) throw @{{ZeroDivisionError}}('integer division or modulo by zero');
        return new $int(y / this['__v']);
    };

    $int['__mul__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        var v = this['__v'] * y;
        if ($min_int <= v && v <= $max_int) {
            return new $int(v);
        }
        if (-$max_float_int < v && v < $max_float_int) {
            return new @{{long}}(v);
        }
        return new @{{long}}(this['__v'])['__mul__'](new @{{long}}(y));
    };

    $int['__rmul__'] = $int['__mul__'];

    $int['__mod__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        if (y == 0) throw @{{ZeroDivisionError}}('integer division or modulo by zero');
        return new $int(this['__v'] % y);
    };

    $int['__rmod__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        if (this['__v'] == 0) throw @{{ZeroDivisionError}}('integer division or modulo by zero');
        return new $int(y % this['__v']);
    };

    $int['__pow__'] = function (y) {
        if (y['__number__'] != 0x02) return @{{NotImplemented}};
        y = y['__v'];
        var v = Math['pow'](this['__v'], y);
        if ($min_int <= v && v <= $max_int) {
            return new $int(v);
        }
        if (-$max_float_int < v && v < $max_float_int) {
            return new @{{long}}(v);
        }
        return new @{{long}}(this['__v'])['__pow__'](new @{{long}}(y));
    };
})();
""")

# This is the python long implementation. See:
#  - Include/longintrepr.h
#  - Include/longobject.h
#  - Objects/longobject.c
JS("""
(function(){

    var $log2 = Math['log'](2);
    var $DigitValue = [
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37,
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37,
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37,
            0,  1,  2,  3,  4,  5,  6,  7,  8,  9,  37, 37, 37, 37, 37, 37,
            37, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
            25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 37, 37, 37, 37, 37,
            37, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
            25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 37, 37, 37, 37, 37,
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37,
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37,
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37,
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37,
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37,
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37,
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37,
            37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37, 37
    ];
    var $log_base_PyLong_BASE = new Array();
    var $convwidth_base = new Array();
    var $convmultmax_base = new Array();
    for (var i = 0; i < 37; i++) {
        $log_base_PyLong_BASE[i] = $convwidth_base[i] = $convmultmax_base[i] = 0;
    }
    var $cdigit = '0123456789abcdefghijklmnopqrstuvwxyz';


    var PyLong_SHIFT = 15;
    var PyLong_MASK = 0x7fff;
    var PyLong_BASE = 0x8000;

    var KARATSUBA_CUTOFF = 70;
    var KARATSUBA_SQUARE_CUTOFF = (2 * KARATSUBA_CUTOFF);

    var FIVEARY_CUTOFF = 8;

    function array_eq(a, b, n) {
        for (var i = 0 ; i < n; i++) {
            if (a[i] != b[i])
                return false;
        }
        return true;
    }

    function long_normalize(v) {
        var j = v['ob_size'] < 0 ? -v['ob_size']:v['ob_size'];
        var i = j;
        while (i > 0 && v['ob_digit'][i-1] == 0) {
            i--;
        }
        if (i != j) {
            v['ob_size'] = v['ob_size'] < 0 ? -i:i;
        }
        return v;
    }

    function AsScaledDouble(vv) {
        var multiplier = PyLong_BASE; // 1L << PyLong_SHIFT == 1 << 15
        var neg, i, x, nbitsneeded;

        if (vv['ob_size'] < 0) {
            i = -vv['ob_size'];
            neg = true;
        } else if (vv['ob_size'] > 0) {
            i = vv['ob_size'];
            neg = false;
        } else {
            return [0.0, 0];
        }
        --i;
        x = vv['ob_digit'][i];
        nbitsneeded = 56;
        while (i > 0 && nbitsneeded > 0) {
            --i;
            x = x * multiplier + vv['ob_digit'][i];
            nbitsneeded -= PyLong_SHIFT;
        }
        if (neg) {
            return [-x, i];
        }
        return [x, i];
    }

    function v_iadd(x, m, y, n) {
        var i, carry = 0;
        for (i = 0; i < n; ++i) {
                carry += x[i] + y[i];
                x[i] = carry & PyLong_MASK;
                carry >>= PyLong_SHIFT;
        }
        for (; carry && i < m; ++i) {
                carry += x[i];
                x[i] = carry & PyLong_MASK;
                carry >>= PyLong_SHIFT;
        }
        return carry;
    }

    function v_isub(x, m, y, n) {
        var i, borrow = 0;
        for (i = 0; i < n; ++i) {
                borrow = x[i] - y[i] - borrow;
                x[i] = borrow & PyLong_MASK;
                borrow >>= PyLong_SHIFT;
                borrow &= 1;
        }
        for (; borrow && i < m; ++i) {
                borrow = x[i] - borrow;
                x[i] = borrow & PyLong_MASK;
                borrow >>= PyLong_SHIFT;
                borrow &= 1;
        }
        return borrow;
    }

    //function mul1(a, n) {
    //    return muladd1(a, n, 0);
    //}

    function muladd1(z, a, n, extra) {
        var size_a = a['ob_size'] < 0 ? -a['ob_size'] : a['ob_size'];
        var carry = extra, i;

        for (i = 0; i < size_a; ++i) {
                carry += a['ob_digit'][i] * n;
                z['ob_digit'][i] = carry & PyLong_MASK;
                carry >>= PyLong_SHIFT;
        }
        z['ob_digit'][i] = carry;
        z['ob_size'] = i + 1;
        return long_normalize(z);
    }

    function inplace_divrem1(pout, pin, pout_idx, pin_idx, size, n) {
        var rem = 0, hi = 0;
        pin_idx += size;
        pout_idx += size;
        while (pin_idx > pin['length']) {
            --size;
            --pin_idx;
            pout[--pout_idx] = 0;
        }
        while (--size >= 0) {
            rem = (rem << PyLong_SHIFT) + pin[--pin_idx];
            pout[--pout_idx] = hi = Math['floor'](rem / n);
            rem -= hi * n;
        }
        return [rem, pout_idx, pin_idx];
    }

    function divrem1(a, n, prem) {
        var size = a['ob_size'] < 0 ? -a['ob_size'] : a['ob_size'];
        var z = new $long(0);

        prem[0] = inplace_divrem1(z['ob_digit'], a['ob_digit'], 0, 0, size, n)[0];
        z['ob_size'] = size;
        return long_normalize(z);
    }

    function Format(aa, base, addL, newstyle, noBase) {
        var text, str, p, i, bits, sz, rem, sign = '';
        var c_0 = "0"['charCodeAt'](0);
        var c_a = "a"['charCodeAt'](0);
        base = base['valueOf']();

        if (aa['ob_size'] == 0) {
            if (addL) {
                text = "0L";
            } else {
                text = "0";
            }
        } else {
            if (aa['ob_size'] < 0) {
                sign = '-';
                size_a = -aa['ob_size'];
            } else {
                size_a = aa['ob_size'];
            }
            i = base;
            bits = 0;
            while (i > 1) {
                ++bits;
                i >>>= 1;
            }
            i = addL ? 6 : 5;
            j = size_a * PyLong_SHIFT + bits - 1;
            sz = Math['floor'](i + j / bits);
            if (j / PyLong_SHIFT < size_a || sz < i) {
                throw @{{OverflowError}}("long is too large to format");
            }
            str = new Array();
            p = sz;
            if (addL) str[--p] = 'L';
            if ((base & (base - 1)) == 0) {
                var accum = 0, accumbits = 0, basebits = 1;
                i = base;
                while ((i >>>= 1) > 1) ++basebits;
                for (i = 0; i < size_a; ++i) {
                    accum |= aa['ob_digit'][i] << accumbits;
                    accumbits += PyLong_SHIFT;
                    while (1) {
                        var cdigit = accum & (base - 1);
                        str[--p] = $cdigit['charAt'](cdigit);
                        accumbits -= basebits;
                        accum >>>= basebits;
                        if (i < size_a-1) {
                            if (accumbits < basebits) break;
                        } else if (accum <= 0) break;
                    }
                }
                text = str['join']("");
            } else {
                // Not 0, and base not a power of 2.
                var scratch, pin, scratch_idx, pin_idx;
                var powbase = base, power = 1, size = size_a;

                while (1) {
                    var newpow = powbase * base;
                    if (newpow >>> PyLong_SHIFT)  /* doesn't fit in a digit */
                        break;
                    powbase = newpow;
                    ++power;
                }
                scratch = aa['ob_digit']['slice'](0);
                pin = aa['ob_digit'];
                scratch_idx = pin_idx = 0;
                do {
                        var ntostore = power;
                        rem = inplace_divrem1(scratch, pin, scratch_idx, pin_idx, size, powbase);
                        scratch_idx = rem[1];
                        rem = rem[0];
                        pin = scratch;
                        pin_idx = 0;
                        if (pin[size - 1] == 0) {
                            --size;
                        }
                        do {
                            var nextrem = Math['floor'](rem / base);
                            str[--p] = $cdigit['charAt'](rem - nextrem * base);
                            rem = nextrem;
                            --ntostore;
                        } while (ntostore && (size || rem));
                } while (size !=0);
                text = str['slice'](p)['join']("");
            }
            text = text['lstrip']('0');
            if (text == "" || text == "L") text = "0" + text;
        }
        if (noBase !== false) {
            switch (base) {
                case 10:
                    break;
                case 2:
                    text = '0b' + text;
                    break;
                case 8:
                    text = (newstyle ? '0o':(aa['ob_size'] ? '0': '')) + text;
                    break;
                case 16:
                    text = '0x' + text;
                    break;
                default:
                    text = base + '#' + text;
                    break;
            }
        }
        return sign + text;
    }

    function long_divrem(a, b, pdiv, prem) {
        var size_a = a['ob_size'] < 0 ? -a['ob_size'] : a['ob_size'];
        var size_b = b['ob_size'] < 0 ? -b['ob_size'] : b['ob_size'];
        var z = null;

        if (size_b == 0) {
            throw @{{ZeroDivisionError}}("long division or modulo by zero");
        }
        if (size_a < size_b ||
            (size_a == size_b &&
             a['ob_digit'][size_a-1] < b['ob_digit'][size_b-1])) {
                // |a| < |b|
                pdiv['ob_size'] = 0;
                prem['ob_digit'] = a['ob_digit']['slice'](0);
                prem['ob_size'] = a['ob_size'];
                return 0;
        }
        if (size_b == 1) {
                rem = [0];
                prem['ob_digit'] = [0];
                prem['ob_size'] = 1;
                z = divrem1(a, b['ob_digit'][0], prem['ob_digit']);
                prem = long_normalize(prem);
        }
        else {
                z = @{{!x_divrem}}(a, b, prem);
        }
        if (z === null) {
            pdiv['ob_size'] = 0;
        } else {
            pdiv['ob_digit'] = z['ob_digit']['slice'](0);
            pdiv['ob_size'] = z['ob_size'];
        }
        if ((a['ob_size'] < 0) != (b['ob_size'] < 0))
                pdiv['ob_size'] = -(pdiv['ob_size']);
        if (a['ob_size'] < 0 && prem['ob_size'] != 0)
                prem['ob_size'] = -prem['ob_size'];
        return 0;
    }

    function x_divrem(v1, w1, prem) {
        var size_w = w1['ob_size'] < 0 ? -w1['ob_size'] : w1['ob_size'];
        var d = Math['floor'](PyLong_BASE / (w1['ob_digit'][size_w-1] + 1));
        var v = muladd1($x_divrem_v, v1, d, 0);
        var w = muladd1($x_divrem_w, w1, d, 0);
        var a, j, k;
        var size_v = v['ob_size'] < 0 ? -v['ob_size'] : v['ob_size'];
        k = size_v - size_w;
        a = new $long(0);
        a['ob_size'] = k + 1;

        for (j = size_v; k >= 0; --j, --k) {
            var vj = (j >= size_v) ? 0 : v['ob_digit'][j];
            var carry = 0;
            var q, i;

            if (vj == w['ob_digit'][size_w-1])
                q = PyLong_MASK;
            else
                q = Math['floor'](((vj << PyLong_SHIFT) + v['ob_digit'][j-1]) /
                        w['ob_digit'][size_w-1]);

            while (w['ob_digit'][size_w-2]*q >
                    ((
                        (vj << PyLong_SHIFT)
                        + v['ob_digit'][j-1]
                        - q*w['ob_digit'][size_w-1]
                                                ) << PyLong_SHIFT)
                    + v['ob_digit'][j-2])
                --q;

            for (i = 0; i < size_w && i+k < size_v; ++i) {
                var z = w['ob_digit'][i] * q;
                var zz = z >>> PyLong_SHIFT;
                carry += v['ob_digit'][i+k] - z
                        + (zz << PyLong_SHIFT);
                v['ob_digit'][i+k] = carry & PyLong_MASK;
                // carry = Py_ARITHMETIC_RIGHT_SHIFT(BASE_TWODIGITS_TYPE, carry, PyLong_SHIFT);
                carry >>= PyLong_SHIFT;
                carry -= zz;
            }

            if (i+k < size_v) {
                carry += v['ob_digit'][i+k];
                v['ob_digit'][i+k] = 0;
            }

            if (carry == 0)
                a['ob_digit'][k] = q;
            else {
                a['ob_digit'][k] = q-1;
                carry = 0;
                for (i = 0; i < size_w && i+k < size_v; ++i) {
                    carry += v['ob_digit'][i+k] + w['ob_digit'][i];
                    v['ob_digit'][i+k] = carry & PyLong_MASK;
                    // carry = Py_ARITHMETIC_RIGHT_SHIFT( BASE_TWODIGITS_TYPE, carry, PyLong_SHIFT);
                    carry >>= PyLong_SHIFT;
                }
            }
        } /* for j, k */

        i = divrem1(v, d, prem);
        prem['ob_digit'] = i['ob_digit']['slice'](0);
        prem['ob_size'] = i['ob_size'];
        return long_normalize(a);
    }

    function x_add(a, b) {
        var size_a = a['ob_size'] < 0 ? -a['ob_size'] : a['ob_size'];
        var size_b = b['ob_size'] < 0 ? -b['ob_size'] : b['ob_size'];
        var z = new $long(0);
        var i;
        var carry = 0;

        if (size_a < size_b) {
            var temp = a;
            a = b;
            b = temp;
            temp = size_a;
            size_a = size_b;
            size_b = temp;
        }
        for (i = 0; i < size_b; ++i) {
                carry += a['ob_digit'][i] + b['ob_digit'][i];
                z['ob_digit'][i] = carry & PyLong_MASK;
                carry >>>= PyLong_SHIFT;
        }
        for (; i < size_a; ++i) {
                carry += a['ob_digit'][i];
                z['ob_digit'][i] = carry & PyLong_MASK;
                carry >>>= PyLong_SHIFT;
        }
        z['ob_digit'][i] = carry;
        z['ob_size'] = i+1;
        return long_normalize(z);
    }

    function x_sub(a, b) {
        var size_a = a['ob_size'] < 0 ? -a['ob_size'] : a['ob_size'];
        var size_b = b['ob_size'] < 0 ? -b['ob_size'] : b['ob_size'];
        var z = new $long(0);
        var i;
        var borrow = 0;
        var sign = 1;

        if (size_a < size_b) {
            var temp = a;
            a = b;
            b = temp;
            temp = size_a;
            size_a = size_b;
            size_b = temp;
            sign = -1;
        } else if (size_a == size_b) {
            i = size_a;
            while (--i >= 0 && a['ob_digit'][i] == b['ob_digit'][i])
                ;
            if (i < 0)
                return z;
            if (a['ob_digit'][i] < b['ob_digit'][i]) {
                var temp = a;
                a = b;
                b = temp;
                temp = size_a;
                size_a = size_b;
                size_b = temp;
                sign = -1;
            }
            size_a = size_b = i+1;
        }
        for (i = 0; i < size_b; ++i) {
                borrow = a['ob_digit'][i] - b['ob_digit'][i] - borrow;
                z['ob_digit'][i] = borrow & PyLong_MASK;
                borrow >>>= PyLong_SHIFT;
                borrow &= 1;
        }
        for (; i < size_a; ++i) {
                borrow = a['ob_digit'][i] - borrow;
                z['ob_digit'][i] = borrow & PyLong_MASK;
                borrow >>>= PyLong_SHIFT;
                borrow &= 1;
        }
        z['ob_size'] = i;
        if (sign < 0)
            z['ob_size'] = -(z['ob_size']);
        return long_normalize(z);
    }

    function x_mul(a, b) {
        var size_a = a['ob_size'] < 0 ? -a['ob_size'] : a['ob_size'];
        var size_b = b['ob_size'] < 0 ? -b['ob_size'] : b['ob_size'];
        var z = new $long(0);
        var i, s;

        z['ob_size'] = size_a + size_b;
        for (i = 0; i < z['ob_size']; i++) {
            z['ob_digit'][i] = 0;
        }
        if (size_a == size_b && array_eq(a['ob_digit'], b['ob_digit'], size_a)) {
            // Efficient squaring per HAC, Algorithm 14['16']:
            for (i = 0; i < size_a; ++i) {
                var carry;
                var f = a['ob_digit'][i];
                var pz = (i << 1);
                var pa = i + 1;
                var paend = size_a;

                carry = z['ob_digit'][pz] + f * f;
                z['ob_digit'][pz++] = carry & PyLong_MASK;
                carry >>>= PyLong_SHIFT;

                f <<= 1;
                while (pa < paend) {
                    carry += z['ob_digit'][pz] + a['ob_digit'][pa++] * f;
                    z['ob_digit'][pz++] = carry & PyLong_MASK;
                    carry >>>= PyLong_SHIFT;
                }
                if (carry) {
                    carry += z['ob_digit'][pz];
                    z['ob_digit'][pz++] = carry & PyLong_MASK;
                    carry >>>= PyLong_SHIFT;
                }
                if (carry) {
                    z['ob_digit'][pz] += carry & PyLong_MASK;
                }
            }
        }
        else {  // a is not the same as b -- gradeschool long mult
            for (i = 0; i < size_a; ++i) {
                var carry = 0;
                var f = a['ob_digit'][i];
                var pz = i;
                var pb = 0;
                var pbend = size_b;

                while (pb < pbend) {
                    carry += z['ob_digit'][pz] + b['ob_digit'][pb++] * f;
                    z['ob_digit'][pz++] = carry & PyLong_MASK;
                    carry >>>= PyLong_SHIFT;
                }
                if (carry) {
                    z['ob_digit'][pz] += carry & PyLong_MASK;
                }
            }
        }
        z['ob_size'] = z['ob_digit']['length'];
        return long_normalize(z);
    }

    function l_divmod(v, w, pdiv, pmod) {
        var div = $l_divmod_div,
            mod = $l_divmod_mod;

        if (long_divrem(v, w, div, mod) < 0)
                return -1;
        if (pdiv == null && pmod == null) return 0;

        if ((mod['ob_size'] < 0 && w['ob_size'] > 0) ||
            (mod['ob_size'] > 0 && w['ob_size'] < 0)) {
                mod = mod['__add__'](w);
                div = div['__sub__']($const_long_1);
        }
        if (pdiv !== null) {
            pdiv['ob_digit'] = div['ob_digit']['slice'](0);
            pdiv['ob_size'] = div['ob_size'];
        }
        if (pmod !== null) {
            pmod['ob_digit'] = mod['ob_digit']['slice'](0);
            pmod['ob_size'] = mod['ob_size'];
        }
        return 0;
    }



    /* XXX do not convert to @{{long}} - this is correct */
    var $long = pyjslib['long'] = function(value, radix) {
        var v, i;
        if (!radix || radix['valueOf']() == 0) {
            if (typeof value == 'undefined') {
                throw @{{TypeError}}("long() takes at least 1 argument");
            }
            switch (value['__number__']) {
                case 0x01:
                    value = value > 0 ? Math['floor'](value) : Math['ceil'](value);
                    break;
                case 0x02:
                    break;
                case 0x04:
                    return value;
            }
            radix = null;
        }
        if (typeof this != 'object' || this['__number__'] != 0x04) return new $long(value, radix);

        v = value;
        this['ob_size'] = 0;
        this['ob_digit'] = new Array();
        if (v['__number__']) {
            if (radix) {
                throw @{{TypeError}}("long() can't convert non-string with explicit base");
            }
            if (v['__number__'] == 0x04) {
                var size = v['ob_size'] < 0 ? -v['ob_size']:v['ob_size'];
                for (var i = 0; i < size; i++) {
                    this['ob_digit'][i] = v['ob_digit'][i];
                }
                this['ob_size'] = v['ob_size'];
                return this;
            }
            if (v['__number__'] == 0x02) {
                var neg = false;
                var ndig = 0;
                v = v['valueOf']();

                if (v < 0) {
                    v = -v;
                    neg = true;
                }
                // Count the number of Python digits.
                var t = v;
                while (t) {
                    this['ob_digit'][ndig] = t & PyLong_MASK;
                    t >>>= PyLong_SHIFT;
                    ++ndig;
                }
                this['ob_size'] = neg ? -ndig : ndig;
                return this;
            }
            if (v['__number__'] == 0x01) {
                var ndig, frac, expo, bits;
                var neg = false;

                if (isNaN(v)) {
                    throw @{{ValueError}}('cannot convert float NaN to integer');
                }
                if (!isFinite(v)) {
                    throw @{{OverflowError}}('cannot convert float infinity to integer');
                }
                if (v == 0) {
                    this['ob_digit'][0] = 0;
                    this['ob_size'] = 0;
                    return this;
                }
                if (v < 0) {
                    v = -v;
                    neg = true;
                }
                // frac = frexp(dval, &expo); // dval = frac*2**expo; 0.0 <= frac < 1.0
                if (v == 0) {
                    frac = 0;
                    expo = 0;
                } else {
                    expo = Math['log'](v)/$log2;
                    expo = (expo < 0 ? Math['ceil'](expo):Math['floor'](expo)) + 1;
                    frac = v / Math['pow'](2.0, expo);
                }
                if (expo <= 0) {
                    return this;
                }
                ndig = Math['floor']((expo-1) / PyLong_SHIFT) + 1;
                // ldexp(a,b) == a * (2**b)
                frac = frac * Math['pow'](2.0, ((expo-1) % PyLong_SHIFT) + 1);
                for (var i = ndig; --i >= 0;) {
                    bits = Math['floor'](frac);
                    this['ob_digit'][i] = bits;
                    frac -= bits;
                    frac = frac * Math['pow'](2.0, PyLong_SHIFT);
                }
                this['ob_size'] = neg ? -ndig : ndig;
                return this;
            }
            throw @{{ValueError}}('cannot convert ' + @{{repr}}(@{{value}}) + 'to integer');
        } else if (typeof v == 'string') {
            var nchars;
            var text = value['lstrip']();
            var i = 0;
            var neg = false;

            switch (text['charAt'](0)) {
                case '-':
                    neg = true;
                case '+':
                    text = text['slice'](1)['lstrip']();
            }

            if (!radix) {
                if (text == '0' || text['charAt'](0) != '0') {
                    radix = 10;
                } else {
                    switch (text['charAt'](1)) {
                        case 'x':
                        case 'X':
                            radix = 16;
                            break;
                        case 'o':
                        case 'O':
                            radix = 8;
                            break;
                        case 'b':
                        case 'B':
                            radix = 2;
                            break;
                        default:
                            radix = 8;
                            break;
                    }
                }
            } else if (radix < 1 || radix > 36) {
                throw @{{ValueError}}("long() arg 2 must be >= 2 and <= 36");
            }
            if (text['charAt'](0) == '0' && text['length'] > 1) {
                switch (text['charAt'](1)) {
                    case 'x':
                    case 'X':
                        if (radix == 16) text = text['slice'](2);
                        break;
                    case 'o':
                    case 'O':
                        if (radix == 8) text = text['slice'](2);
                        break;
                    case 'b':
                    case 'B':
                        if (radix == 2) text = text['slice'](2);
                        break;

                }
            }
            if ((radix & (radix - 1)) == 0) {
                // binary base: 2, 4, 8, ...
                var n, bits_per_char, accum, bits_in_accum, k, pdigit;
                var p = 0;

                n = radix;
                for (bits_per_char = -1; n; ++bits_per_char) {
                    n >>>= 1;
                }
                n = 0;
                while ($DigitValue[text['charCodeAt'](p)] < radix) {
                    p++;
                }
                nchars = p;
                n = p * bits_per_char + PyLong_SHIFT-1; //14 = PyLong_SHIFT - 1
                if (n / bits_per_char < p) {
                    throw @{{ValueError}}("long string too large to convert");
                }
                this['ob_size'] = n = Math['floor'](n/PyLong_SHIFT);
                for (var i = 0; i < n; i++) {
                    this['ob_digit'][i] = 0;
                }
                // Read string from right, and fill in long from left
                accum = 0;
                bits_in_accum = 0;
                pdigit = 0;
                while (--p >= 0) {
                    k = $DigitValue[text['charCodeAt'](p)];
                    accum |= k << bits_in_accum;
                    bits_in_accum += bits_per_char;
                    if (bits_in_accum >= PyLong_SHIFT) {
                        this['ob_digit'][pdigit] = accum & PyLong_MASK;
                        pdigit++;
                        accum >>>= PyLong_SHIFT;
                        bits_in_accum -= PyLong_SHIFT;
                    }
                }
                if (bits_in_accum) {
                    this['ob_digit'][pdigit++] = accum;
                }
                while (pdigit < n) {
                    this['ob_digit'][pdigit++] = 0;
                }
                long_normalize(this);
            } else {
                // Non-binary bases (such as radix == 10)
                var c, i, convwidth, convmultmax, convmult, pz, pzstop, scan, size_z;

                if ($log_base_PyLong_BASE[radix] == 0.0) {
                    var i = 1;
                    var convmax = radix;
                    $log_base_PyLong_BASE[radix] = Math['log'](radix) / Math['log'](PyLong_BASE);
                    while (1) {
                        var next = convmax * radix;
                        if (next > PyLong_BASE) break;
                        convmax = next;
                        ++i;
                    }
                    $convmultmax_base[radix] = convmax;
                    $convwidth_base[radix] = i;
                }
                scan = 0;
                while ($DigitValue[text['charCodeAt'](scan)] < radix)
                    ++scan;
                nchars = scan;
                size_z = scan * $log_base_PyLong_BASE[radix] + 1;
                for (var i = 0; i < size_z; i ++) {
                    this['ob_digit'][i] = 0;
                }
                this['ob_size'] = 0;
                convwidth = $convwidth_base[radix];
                convmultmax = $convmultmax_base[radix];
                for (var str = 0; str < scan;) {
                    c = $DigitValue[text['charCodeAt'](str++)];
                    for (i = 1; i < convwidth && str != scan; ++i, ++str) {
                        c = c * radix + $DigitValue[text['charCodeAt'](str)];
                    }
                    convmult = convmultmax;
                    if (i != convwidth) {
                        convmult = radix;
                        for ( ; i > 1; --i) convmult *= radix;
                    }
                    pz = 0;
                    pzstop = this['ob_size'];
                    for (; pz < pzstop; ++pz) {
                        c += this['ob_digit'][pz] * convmult;
                        this['ob_digit'][pz] = c & PyLong_MASK;
                        c >>>= PyLong_SHIFT;
                    }
                    if (c) {
                        if (this['ob_size'] < size_z) {
                            this['ob_digit'][pz] = c;
                            this['ob_size']++;
                        } else {
                            this['ob_digit'][this['ob_size']] = c;
                        }
                    }
                }
            }
            text = text['slice'](nchars);
            if (neg) this['ob_size'] = -this['ob_size'];
            if (text['charAt'](0) == 'l' || text['charAt'](0) == 'L') text = text['slice'](1);
            text = text['lstrip']();
            if (text['length'] === 0) {
                return this;
            }
            throw @{{ValueError}}("invalid literal for long() with base " +
                                     @{{!radix}} + ": " + @{{!value}});
        } else {
            throw @{{TypeError}}("TypeError: long() argument must be a string or a number");
        }
        if (isNaN(v) || !isFinite(v)) {
            throw @{{ValueError}}("invalid literal for long() with base " + @{{!radix}} + ": '" + @{{!v}} + "'");
        }
        return this;
    };
    $long['__init__'] = function () {};
    $long['__number__'] = 0x04;
    $long['__name__'] = 'long';
    $long['prototype'] = $long;
    $long['__class__'] = $long;
    $long['ob_size'] = 0;

    $long['toExponential'] = function (fractionDigits) {
        return (typeof fractionDigits == 'undefined' || fractionDigits === null) ? this['__v']['toExponential']() : this['__v']['toExponential'](fractionDigits);
    };

    $long['toFixed'] = function (digits) {
        return (typeof digits == 'undefined' || digits === null) ? this['__v']['toFixed']() : this['__v']['toFixed'](digits);
    };

    $long['toLocaleString'] = function () {
        return this['__v']['toLocaleString']();
    };

    $long['toPrecision'] = function (precision) {
        return (typeof precision == 'undefined' || precision === null) ? this['__v']['toPrecision']() : this['__v']['toPrecision'](precision);
    };

    $long['toString'] = function (radix) {
        return (typeof radix == 'undefined' || radix === null) ? Format(this, 10, false, false) : Format(this, radix, false, false, false);
    };

    $long['valueOf'] = function() {
        var x, v;
        x = AsScaledDouble(this);
        // ldexp(a,b) == a * (2**b)
        v = x[0] * Math['pow'](2.0, x[1] * PyLong_SHIFT);
        if (!isFinite(v)) {
            throw @{{OverflowError}}('long int too large to convert to float');
        }
        return v;
    };

    $long['__str__'] = function () {
        if (typeof this == 'function') return "<type '" + this['__name__'] + "'>";
        return Format(this, 10, false, false);
    };

    $long['__repr__'] = function () {
        if (typeof this == 'function') return "<type '" + this['__name__'] + "'>";
        return Format(this, 10, true, false);
    };

    $long['__nonzero__'] = function () {
        return this['ob_size'] != 0;
    };

    $long['__cmp__'] = function (b) {
        var sign;

        if (this['ob_size'] != b['ob_size']) {
            if (this['ob_size'] < b['ob_size']) return -1;
            return 1;
        }
        var i = this['ob_size'] < 0 ? - this['ob_size'] : this['ob_size'];
        while (--i >= 0 && this['ob_digit'][i] == b['ob_digit'][i])
            ;
        if (i < 0) return 0;
        if (this['ob_digit'][i] < b['ob_digit'][i]) {
            if (this['ob_size'] < 0) return 1;
            return -1;
        }
        if (this['ob_size'] < 0) return -1;
        return 1;
    };

    $long['__hash__'] = function () {
        var s = this['__str__']();
        var v = this['valueOf']();
        if (v['toString']() == s) {
            return v;
        }
        return s;
    };

    $long['__invert__'] = function () {
        var x = this['__add__']($const_long_1);
        x['ob_size'] = -x['ob_size'];
        return x;
    };

    $long['__neg__'] = function () {
        var x = new $long(0);
        x['ob_digit'] = this['ob_digit']['slice'](0);
        x['ob_size'] = -this['ob_size'];
        return x;
    };

    $long['__abs__'] = function () {
        if (this['ob_size'] >= 0) return this;
        var x = new $long(0);
        x['ob_digit'] = this['ob_digit']['slice'](0);
        x['ob_size'] = -x['ob_size'];
        return x;
    };

    $long['__lshift'] = function (y) {
        var a, z, wordshift, remshift, oldsize, newsize,
            accum, i, j;
        if (y < 0) {
            throw @{{ValueError}}('negative shift count');
        }
        if (y >= $max_float_int) {
            throw @{{ValueError}}('outrageous left shift count');
        }
        a = this;

        wordshift = Math['floor'](y / PyLong_SHIFT);
        remshift  = y - wordshift * PyLong_SHIFT;

        oldsize = a['ob_size'] < 0 ? -a['ob_size'] : a['ob_size'];
        newsize = oldsize + wordshift;
        if (remshift) ++newsize;
        z = new $long(0);
        z['ob_size'] = a['ob_size'] < 0 ? -newsize : newsize;
        for (i = 0; i < wordshift; i++) {
            z['ob_digit'][i] = 0;
        }
        accum = 0;
        for (i = wordshift, j = 0; j < oldsize; i++, j++) {
            accum |= a['ob_digit'][j] << remshift;
            z['ob_digit'][i] = accum & PyLong_MASK;
            accum >>>= PyLong_SHIFT;
        }
        if (remshift) {
            z['ob_digit'][newsize-1] = accum;
        }
        z = long_normalize(z);
        return z;
    };

    $long['__lshift__'] = function (y) {
        switch (y['__number__']) {
            case 0x01:
                if (y == Math['floor'](y)) return this['__lshift'](y);
                break;
            case 0x02:
                return this['__lshift'](y['__v']);
            case 0x04:
                y = y['valueOf']();
                return this['__lshift'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__rlshift__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return (new $long(y['__v']))['__lshift'](this['valueOf']());
            case 0x04:
                return y['__lshift'](this['valueOf']());
        }
        return @{{NotImplemented}};
    };

    $long['__rshift'] = function (y) {
        var a, z, size, wordshift, newsize, loshift, hishift,
            lomask, himask, i, j;
        if (y['__number__'] != 0x01) {
            y = y['valueOf']();
        } else {
            if (y != Math['floor'](y)) {
                throw @{{TypeError}}("unsupported operand type(s) for >>: 'long' and 'float'");
            }
        }
        if (y < 0) {
            throw @{{ValueError}}('negative shift count');
        }
        if (y >= $max_float_int) {
            throw @{{ValueError}}('shift count too big');
        }
        a = this;
        size = this['ob_size'];
        if (this['ob_size'] < 0) {
            size = -size;
            a = this['__add__']($const_long_1);
            a['ob_size'] = -a['ob_size'];
        }

        wordshift = Math['floor'](y / PyLong_SHIFT);
        newsize = size - wordshift;
        if (newsize <= 0) {
            z = $const_long_0;
        } else {
            loshift = y % PyLong_SHIFT;
            hishift = PyLong_SHIFT - loshift;
            lomask = (1 << hishift) - 1;
            himask = PyLong_MASK ^ lomask;
            z = new $long(0);
            z['ob_size'] = a['ob_size'] < 0 ? -newsize : newsize;
            for (i = 0, j = wordshift; i < newsize; i++, j++) {
                z['ob_digit'][i] = (a['ob_digit'][j] >>> loshift) & lomask;
                if (i+1 < newsize) {
                    z['ob_digit'][i] |=
                      (a['ob_digit'][j+1] << hishift) & himask;
                }
            }
            z = long_normalize(z);
        }

        if (this['ob_size'] < 0) {
            z = z['__add__']($const_long_1);
            z['ob_size'] = -z['ob_size'];
        }
        return z;
    };

    $long['__rshift__'] = function (y) {
        switch (y['__number__']) {
            case 0x01:
                if (y == Math['floor'](y)) return this['__rshift'](y);
                break;
            case 0x02:
                return this['__rshift'](y['__v']);
            case 0x04:
                y = y['valueOf']();
                return this['__rshift'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__rrshift__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return (new $long(y['__v']))['__rshift'](this['valueOf']());
            case 0x04:
                return y['__rshift'](this['valueOf']());
        }
        return @{{NotImplemented}};
    };

    $long['__and'] = function (b) {
        var a, maska, maskb, negz, size_a, size_b, size_z,
            i, z, diga, digb, v, op;

        a = this;

        if (a['ob_size'] < 0) {
            a = a['__invert__']();
            maska = PyLong_MASK;
        } else {
            maska = 0;
        }
        if (b['ob_size'] < 0) {
            b = b['__invert__']();
            maskb = PyLong_MASK;
        } else {
            maskb = 0;
        }
        negz = 0;


            op = '&';
            if (maska && maskb) {
                op = '|';
                maska ^= PyLong_MASK;
                maskb ^= PyLong_MASK;
                negz = -1;
            }


        size_a = a['ob_size'];
        size_b = b['ob_size'];
        size_z = op == '&'
                    ? (maska
                        ? size_b
                        : (maskb ? size_a : (size_a < size_b ? size_a : size_b)))
                    : (size_a > size_b ? size_a : size_b);
        z = new $long(0);
        z['ob_size'] = size_z;

        switch (op) {
            case '&':
                for (i = 0; i < size_z; ++i) {
                    diga = (i < size_a ? a['ob_digit'][i] : 0) ^ maska;
                    digb = (i < size_b ? b['ob_digit'][i] : 0) ^ maskb;
                    z['ob_digit'][i] = diga & digb;
                }
                break;
            case '|':
                for (i = 0; i < size_z; ++i) {
                    diga = (i < size_a ? a['ob_digit'][i] : 0) ^ maska;
                    digb = (i < size_b ? b['ob_digit'][i] : 0) ^ maskb;
                    z['ob_digit'][i] = diga | digb;
                }
                break;
            case '^':
                for (i = 0; i < size_z; ++i) {
                    diga = (i < size_a ? a['ob_digit'][i] : 0) ^ maska;
                    digb = (i < size_b ? b['ob_digit'][i] : 0) ^ maskb;
                    z['ob_digit'][i] = diga ^ digb;
                }
                break;
        }
        z = long_normalize(z);
        if (negz == 0) {
            return z;
        }
        return z['__invert__']();
    };

    $long['__and__'] = function (y) {
        switch (y['__number__']) {
            case 0x01:
                if (y == Math['floor'](y)) return this['__and'](new $long(y));
                break;
            case 0x02:
                return this['__and'](new $long(y['__v']));
            case 0x04:
                return this['__and'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__rand__'] = $long['__and__'];

    $long['__xor'] = function (b) {
        var a,maska, maskb, negz, size_a, size_b, size_z,
            i, z, diga, digb, v, op;

        a = this;

        if (a['ob_size'] < 0) {
            a = a['__invert__']();
            maska = PyLong_MASK;
        } else {
            maska = 0;
        }
        if (b['ob_size'] < 0) {
            b = b['__invert__']();
            maskb = PyLong_MASK;
        } else {
            maskb = 0;
        }
        negz = 0;


            op = '^';
            if (maska != maskb) {
                maska ^= PyLong_MASK;
                negz = -1;
            }


        size_a = a['ob_size'];
        size_b = b['ob_size'];
        size_z = op == '&'
                    ? (maska
                        ? size_b
                        : (maskb ? size_a : (size_a < size_b ? size_a : size_b)))
                    : (size_a > size_b ? size_a : size_b);
        z = new $long(0);
        z['ob_size'] = size_z;

        switch (op) {
            case '&':
                for (i = 0; i < size_z; ++i) {
                    diga = (i < size_a ? a['ob_digit'][i] : 0) ^ maska;
                    digb = (i < size_b ? b['ob_digit'][i] : 0) ^ maskb;
                    z['ob_digit'][i] = diga & digb;
                }
                break;
            case '|':
                for (i = 0; i < size_z; ++i) {
                    diga = (i < size_a ? a['ob_digit'][i] : 0) ^ maska;
                    digb = (i < size_b ? b['ob_digit'][i] : 0) ^ maskb;
                    z['ob_digit'][i] = diga | digb;
                }
                break;
            case '^':
                for (i = 0; i < size_z; ++i) {
                    diga = (i < size_a ? a['ob_digit'][i] : 0) ^ maska;
                    digb = (i < size_b ? b['ob_digit'][i] : 0) ^ maskb;
                    z['ob_digit'][i] = diga ^ digb;
                }
                break;
        }
        z = long_normalize(z);
        if (negz == 0) {
            return z;
        }
        return z['__invert__']();
    };

    $long['__xor__'] = function (y) {
        switch (y['__number__']) {
            case 0x01:
                if (y == Math['floor'](y)) return this['__xor'](new $long(y));
                break;
            case 0x02:
                return this['__xor'](new $long(y['__v']));
            case 0x04:
                return this['__xor'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__rxor__'] = $long['__xor__'];

    $long['__or'] = function (b) {
        var a, maska, maskb, negz, size_a, size_b, size_z,
            i, z, diga, digb, v, op;

        a = this;

        if (a['ob_size'] < 0) {
            a = a['__invert__']();
            maska = PyLong_MASK;
        } else {
            maska = 0;
        }
        if (b['ob_size'] < 0) {
            b = b['__invert__']();
            maskb = PyLong_MASK;
        } else {
            maskb = 0;
        }
        negz = 0;


            op = '|';
            if (maska || maskb) {
                op = '&';
                maska ^= PyLong_MASK;
                maskb ^= PyLong_MASK;
                negz = -1;
            }


        size_a = a['ob_size'];
        size_b = b['ob_size'];
        size_z = op == '&'
                    ? (maska
                        ? size_b
                        : (maskb ? size_a : (size_a < size_b ? size_a : size_b)))
                    : (size_a > size_b ? size_a : size_b);
        z = new $long(0);
        z['ob_size'] = size_z;

        switch (op) {
            case '&':
                for (i = 0; i < size_z; ++i) {
                    diga = (i < size_a ? a['ob_digit'][i] : 0) ^ maska;
                    digb = (i < size_b ? b['ob_digit'][i] : 0) ^ maskb;
                    z['ob_digit'][i] = diga & digb;
                }
                break;
            case '|':
                for (i = 0; i < size_z; ++i) {
                    diga = (i < size_a ? a['ob_digit'][i] : 0) ^ maska;
                    digb = (i < size_b ? b['ob_digit'][i] : 0) ^ maskb;
                    z['ob_digit'][i] = diga | digb;
                }
                break;
            case '^':
                for (i = 0; i < size_z; ++i) {
                    diga = (i < size_a ? a['ob_digit'][i] : 0) ^ maska;
                    digb = (i < size_b ? b['ob_digit'][i] : 0) ^ maskb;
                    z['ob_digit'][i] = diga ^ digb;
                }
                break;
        }
        z = long_normalize(z);
        if (negz == 0) {
            return z;
        }
        return z['__invert__']();
    };

    $long['__or__'] = function (y) {
        switch (y['__number__']) {
            case 0x01:
                if (y == Math['floor'](y)) return this['__or'](new $long(y));
                break;
            case 0x02:
                return this['__or'](new $long(y['__v']));
            case 0x04:
                return this['__or'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__ror__'] = $long['__or__'];

    $long['__oct__'] = function () {
        return Format(this, 8, true, false);
    };

    $long['__hex__'] = function () {
        return Format(this, 16, true, false);
    };

    $long['__add'] = function (b) {
        var a = this, z;
        if (a['ob_size'] < 0) {
            if (b['ob_size'] < 0) {
                z = x_add(a, b);
                z['ob_size'] = -(z['ob_size']);
            }
            else {
                z = x_sub(b, a);
            }
        }
        else {
            z = b['ob_size'] < 0 ? x_sub(a, b) : x_add(a, b);
        }
        return z;
    };

    $long['__add__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return this['__add'](new $long(y['__v']));
            case 0x04:
                return this['__add'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__radd__'] = $long['__add__'];

    $long['__sub'] = function (b) {
        var a = this, z;
        if (a['ob_size'] < 0) {
            z = b['ob_size'] < 0 ? x_sub(a, b) : x_add(a, b);
            z['ob_size'] = -(z['ob_size']);
        }
        else {
            z = b['ob_size'] < 0 ?  x_add(a, b) : x_sub(a, b);
        }
        return z;
    };

    $long['__sub__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return this['__sub'](new $long(y['__v']));
            case 0x04:
                return this['__sub'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__rsub__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return (new $long(y['__v']))['__sub'](this);
            case 0x04:
                return y['__sub'](this);
        }
        return @{{NotImplemented}};
    };

    $long['__mul'] = function (b) {
        //var z = k_mul(a, b);
        var z = x_mul(this, b);
        if ((this['ob_size'] ^ b['ob_size']) < 0)
            z['ob_size'] = -(z['ob_size']);
        return z;
    };

    $long['__mul__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return this['__mul'](new $long(y['__v']));
            case 0x04:
                return this['__mul'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__rmul__'] = $long['__mul__'];

    $long['__div'] = function (b) {
        var div = new $long(0);
        l_divmod(this, b, div, null);
        return div;
    };

    $long['__div__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return this['__sub'](new $long(y['__v']));
            case 0x04:
                return this['__sub'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__rdiv__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return (new $long(y['__v']))['__div'](this);
            case 0x04:
                return y['__div'](this);
        }
        return @{{NotImplemented}};
    };

    $long['__mod'] = function (b) {
        var mod = new $long(0);
        l_divmod(this, b, null, mod);
        return mod;
    };

    $long['__mod__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return this['__mod'](new $long(y['__v']));
            case 0x04:
                return this['__mod'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__rmod__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return (new $long(y['__v']))['__mod'](this);
            case 0x04:
                return y['__mod'](this);
        }
        return @{{NotImplemented}};
    };

    $long['__divmod'] = function (b) {
        var div = new $long(0);
        var mod = new $long(0);
        l_divmod(this, b, div, mod);
        return @{{tuple}}([div, mod]);
    };

    $long['__divmod__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return this['__divmod'](new $long(y['__v']));
            case 0x04:
                return this['__divmod'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__rdivmod__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return (new $long(y['__v']))['__divmod'](this);
            case 0x04:
                return y['__divmod'](this);
        }
        return @{{NotImplemented}};
    };

    $long['__floordiv'] = function (b) {
        var div = new $long(0);
        l_divmod(this, b, div, null);
        return div;
    };

    $long['__floordiv__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return this['__floordiv'](new $long(y['__v']));
            case 0x04:
                return this['__floordiv'](y);
        }
        return @{{NotImplemented}};
    };

    $long['__rfloordiv__'] = function (y) {
        switch (y['__number__']) {
            case 0x02:
                return (new $long(y['__v']))['__floordiv'](this);
            case 0x04:
                return y['__floordiv'](this);
        }
        return @{{NotImplemented}};
    };

    $long['__pow'] = function (w, x) {
        var v = this;
        var a, b, c, negativeOutput = 0, z, i, j, k, temp, bi;
        var table = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                     0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0];

        a = this;
        b = w['__number__'] == 0x04 ? w : new $long(w);
        if (x === null || typeof x == 'undefined') {
            c = null;
        } else {
            c = x['__number__'] == 0x04 ? x : new $long(x);
        }

        if (b['ob_size'] < 0) {
            if (c !== null) {
                throw @{{TypeError}}("pow() 2nd argument cannot be negative when 3rd argument specified");
            }
            return Math['pow'](v['valueOf'](), w['valueOf']());
        }

        if (c !== null) {
            if (c['ob_size'] == 0) {
                throw @{{ValueError}}("pow() 3rd argument cannot be 0");
            }
            if (c['ob_size'] < 0) {
                negativeOutput = 1;
                temp = $pow_temp_c;
                temp['ob_digit'] = c['ob_digit']['slice'](0);
                temp['ob_size'] = -c['ob_size'];
                c = temp;
            }
            if (c['ob_size'] == 1 && c['ob_digit'][0] == 1) {
                return $const_long_0;
            }
            if (a['ob_size'] < 0) {
                temp = $pow_temp_a;
                l_divmod(a, c, null, temp);
                a = temp;
            }
        }
        z = new $long(1);
        temp = $pow_temp_z;
        if (b['ob_size'] <= FIVEARY_CUTOFF) {
            for (i = b['ob_size'] - 1; i >= 0; --i) {
                bi = b['ob_digit'][i];
                for (j = 1 << (PyLong_SHIFT-1); j != 0; j >>>= 1) {
                    z = z['__mul'](z);
                    if (c !== null) {
                        l_divmod(z, c, null, temp);
                        z['ob_digit'] = temp['ob_digit']['slice'](0);
                        z['ob_size'] = temp['ob_size'];
                    }
                    if (bi & j) {
                        z = z['__mul'](a);
                        if (c !== null) {
                            l_divmod(z, c, null, temp);
                            z['ob_digit'] = temp['ob_digit']['slice'](0);
                            z['ob_size'] = temp['ob_size'];
                        }
                    }
                }
            }
        } else {
            table[0] = z;
            for (i = 1; i < 32; ++i) {
                table[i] = table[i-1]['__mul'](a);
                if (c !== null) {
                    l_divmod(table[i], c, null, temp);
                    table[i]['ob_digit'] = temp['ob_digit']['slice'](0);
                    table[i]['ob_size'] = temp['ob_size'];
                }
            }
            for (i = b['ob_size'] - 1; i >= 0; --i) {
                bi = b['ob_digit'][i];
                for (j = PyLong_SHIFT - 5; j >= 0; j -= 5) {
                    var index = (bi >>> j) & 0x1f;
                    for (k = 0; k < 5; ++k) {
                        z = z['__mul'](z);
                        if (c !== null) {
                            l_divmod(z, c, null, temp);
                            z['ob_digit'] = temp['ob_digit']['slice'](0);
                            z['ob_size'] = temp['ob_size'];
                        }
                    }
                    if (index) {
                        z = z['__mul'](table[index]);
                        if (c !== null) {
                            l_divmod(z, c, null, temp);
                            z['ob_digit'] = temp['ob_digit']['slice'](0);
                            z['ob_size'] = temp['ob_size'];
                        }
                    }
                }
            }
        }

        if ((c !== null) && negativeOutput &&
            (z['ob_size'] != 0) && (c['ob_size'] != 0)) {
            z = z['__sub__'](c);
        }
        return z;
    };

    $long['__pow__'] = function (y, z) {
        switch (y['__number__']) {
            case 0x02:
                if (typeof z == 'undefined')
                    return this['__pow'](new $long(y['__v']), null);
                switch (z['__number']) {
                    case 0x02:
                        return this['__pow'](new $long(y['__v']), new $long(z));
                    case 0x04:
                        return this['__pow'](new $long(y['__v']), z);
                }
                break;
            case 0x04:
                if (typeof z == 'undefined')
                    return this['__pow'](y, null);
                switch (z['__number']) {
                    case 0x02:
                        return this['__pow'](y, new $long(z));
                    case 0x04:
                        return this['__pow'](y, z);
                }
                break;
        }
        return @{{NotImplemented}};
    };


    var $const_long_0 = new $long(0),
        $const_long_1 = new $long(1);
    // Since javascript is single threaded:
    var $l_divmod_div = new $long(0),
        $l_divmod_mod = new $long(0),
        $x_divrem_v = new $long(0),
        $x_divrem_w = new $long(0),
        $pow_temp_a = new $long(0),
        $pow_temp_c = new $long(0),
        $pow_temp_z = new $long(0);
})();
""")


"""@ATTRIB_REMAP_DECLARATION@"""
"""@CONSTANT_DECLARATION@"""

class tuple:
    # Depends on CONSTANT_DECLARATION
    def __init__(self, data=JS("[]")):
        JS("""
        if (@{{data}} === null) {
            throw @{{TypeError}}("'NoneType' is not iterable");
        }
        if (@{{data}}['constructor'] === Array) {
            @{{self}}['__array'] = @{{data}}['slice']();
            return null;
        }
        if (typeof @{{data}}['__iter__'] == 'function') {
            if (typeof @{{data}}['__array'] == 'object') {
                @{{self}}['__array'] = @{{data}}['__array']['slice']();
                return null;
            }
            var iter = @{{data}}['__iter__']();
            if (typeof iter['__array'] == 'object') {
                @{{self}}['__array'] = iter['__array']['slice']();
                return null;
            }
            @{{data}} = [];
            var item, i = 0;
            if (typeof iter['$genfunc'] == 'function') {
                while (typeof (item=iter['next'](true)) != 'undefined') {
                    @{{data}}[i++] = item;
                }
            } else {
                try {
                    while (true) {
                        @{{data}}[i++] = iter['next']();
                    }
                }
                catch (e) {
                    if (!@{{isinstance}}(e, @{{StopIteration}})) throw e;
                }
            }
            @{{self}}['__array'] = @{{data}};
            return null;
        }
        throw @{{TypeError}}("'" + @{{repr}}(@{{data}}) + "' is not iterable");
        """)

    def __hash__(self):
        return '$tuple$' + str(self.__array)

    def __cmp__(self, l):
        if not isinstance(l, tuple):
            return 1
        JS("""
        var n1 = @{{self}}['__array']['length'],
            n2 = @{{l}}['__array']['length'],
            a1 = @{{self}}['__array'],
            a2 = @{{l}}['__array'],
            n, c;
        n = (n1 < n2 ? n1 : n2);
        for (var i = 0; i < n; i++) {
            c = @{{cmp}}(a1[i], a2[i]);
            if (c) return c;
        }
        if (n1 < n2) return -1;
        if (n1 > n2) return 1;
        return 0;""")

    def __getslice__(self, lower, upper):
        JS("""
        if (@{{upper}}==null) return @{{tuple}}(@{{self}}['__array']['slice'](@{{lower}}));
        return @{{tuple}}(@{{self}}['__array']['slice'](@{{lower}}, @{{upper}}));
        """)

    def __getitem__(self, _index):
        JS("""
        var index = @{{_index}}['valueOf']();
        if (typeof index == 'boolean') index = @{{int}}(index);
        if (index < 0) index += @{{self}}['__array']['length'];
        if (index < 0 || index >= @{{self}}['__array']['length']) {
            throw @{{IndexError}}("tuple index out of range");
        }
        return @{{self}}['__array'][index];
        """)

    def __len__(self):
        return INT(JS("""@{{self}}['__array']['length']"""))

    def index(self, value, _start=0):
        JS("""
        var start = @{{_start}}['valueOf']();
        /* if (typeof valueXXX == 'number' || typeof valueXXX == 'string') {
            start = selfXXX['__array']['indexOf'](valueXXX, start);
            if (start >= 0)
                return start;
        } else */ {
            var len = @{{self}}['__array']['length'] >>> 0;

            start = (start < 0)
                    ? Math['ceil'](start)
                    : Math['floor'](start);
            if (start < 0)
                start += len;

            for (; start < len; start++) {
                if ( /*start in selfXXX['__array'] && */
                    @{{cmp}}(@{{self}}['__array'][start], @{{value}}) == 0)
                    return start;
            }
        }
        """)
        raise ValueError("list.index(x): x not in list")

    def __contains__(self, value):
        try:
            self.index(value)
        except ValueError:
            return False
        return True
        #return JS('@{{self}}['__array']['indexOf'](@{{value}})>=0')

    def __iter__(self):
        return JS("new $iter_array(@{{self}}['__array'])")
        JS("""
        var i = 0;
        var l = @{{self}}['__array'];
        return {
            'next': function() {
                if (i >= l['length']) {
                    throw @{{StopIteration}}();
                }
                return l[i++];
            },
            '__iter__': function() {
                return this;
            }
        };
        """)

    def __enumerate__(self):
        return JS("new $enumerate_array(@{{self}}['__array'])")

    def getArray(self):
        """
        Access the javascript Array that is used internally by this list
        """
        return self.__array

    #def __str__(self):
    #    return self.__repr__()
    #See monkey patch at the end of the tuple class definition

    def __repr__(self):
        if callable(self):
            return "<type '%s'>" % self.__name__
        JS("""
        var s = "(";
        for (var i=0; i < @{{self}}['__array']['length']; i++) {
            s += @{{repr}}(@{{self}}['__array'][i]);
            if (i < @{{self}}['__array']['length'] - 1)
                s += ", ";
        }
        if (@{{self}}['__array']['length'] == 1)
            s += ",";
        s += ")";
        return s;
        """)

    def __add__(self, y):
        if not isinstance(y, self):
            raise TypeError("can only concatenate tuple to tuple")
        return tuple(self.__array.concat(y.__array))

    def __mul__(self, n):
        if not JS("@{{n}} !== null && @{{n}}['__number__'] && (@{{n}}['__number__'] != 0x01 || isFinite(@{{n}}))"):
            raise TypeError("can't multiply sequence by non-int")
        a = []
        while n:
            n -= 1
            a.extend(self.__array)
        return a

    def __rmul__(self, n):
        return self.__mul__(n)
JS("@{{tuple}}['__str__'] = @{{tuple}}['__repr__'];")
JS("@{{tuple}}['toString'] = @{{tuple}}['__str__'];")


class NotImplementedType(object):
    def __repr__(self):
        return "<type 'NotImplementedType'>"
    def __str__(self):
        self.__repr__()
    def toString(self):
        self.__repr__()
NotImplemented = NotImplementedType()

JS("""
var $iter_array = function (l) {
    this['__array'] = l;
    this['i'] = -1;
};
$iter_array['prototype']['next'] = function (noStop) {
    if (++this['i'] == this['__array']['length']) {
        if (noStop === true) {
            return;
        }
        throw @{{StopIteration}}();
    }
    return this['__array'][this['i']];
};
$iter_array['prototype']['__iter__'] = function ( ) {
    return this;
};
var $reversed_iter_array = function (l) {
    this['___array'] = l;
    this['i'] = l['length'];
};
$reversed_iter_array['prototype']['next'] = function (noStop) {
    if (--this['i'] == -1) {
        if (noStop === true) {
            return;
        }
        throw @{{StopIteration}}();
    }
    return this['___array'][this['i']];
};
$reversed_iter_array['prototype']['__iter__'] = function ( ) {
    return this;
};
//$reversed_iter_array['prototype']['$genfunc'] = $reversed_iter_array['prototype']['next'];
var $enumerate_array = function (l) {
    this['array'] = l;
    this['i'] = -1;
    this['tuple'] = """)
tuple([0, ""])
JS("""
    this['tl'] = this['tuple']['__array'];
};
$enumerate_array['prototype']['next'] = function (noStop, reuseTuple) {
    if (++this['i'] == this['array']['length']) {
        if (noStop === true) {
            return;
        }
        throw @{{StopIteration}}();
    }
    this['tl'][1] = this['array'][this['i']];
    if (this['tl'][0]['__number__'] == 0x01) {
        this['tl'][0] = this['i'];
    } else {
        this['tl'][0] = new @{{int}}(this['i']);
    }
    return reuseTuple === true ? this['tuple'] : @{{tuple}}(this['tl']);
};
$enumerate_array['prototype']['__iter__'] = function ( ) {
    return this;
};
$enumerate_array['prototype']['$genfunc'] = $enumerate_array['prototype']['next'];
""")
# NOTE: $genfunc is defined to enable faster loop code

class list:
    def __init__(self, data=JS("[]")):
        # Basically the same as extend, but to save expensive function calls...
        JS("""
        if (@{{data}} === null) {
            throw @{{TypeError}}("'NoneType' is not iterable");
        }
        if (@{{data}}['constructor'] === Array) {
            @{{self}}['__array'] = @{{data}}['slice']();
            return null;
        }
        if (typeof @{{data}}['__iter__'] == 'function') {
            if (typeof @{{data}}['__array'] == 'object') {
                @{{self}}['__array'] = @{{data}}['__array']['slice']();
                return null;
            }
            var iter = @{{data}}['__iter__']();
            if (typeof iter['__array'] == 'object') {
                @{{self}}['__array'] = iter['__array']['slice']();
                return null;
            }
            @{{data}} = [];
            var item, i = 0;
            if (typeof iter['$genfunc'] == 'function') {
                while (typeof (item=iter['next'](true)) != 'undefined') {
                    @{{data}}[i++] = item;
                }
            } else {
                try {
                    while (true) {
                        @{{data}}[i++] = iter['next']();
                    }
                }
                catch (e) {
                    if (!@{{isinstance}}(e, @{{StopIteration}})) throw e;
                }
            }
            @{{self}}['__array'] = @{{data}};
            return null;
        }
        throw @{{TypeError}}("'" + @{{repr}}(@{{data}}) + "' is not iterable");
        """)

    def __hash__(self):
        raise TypeError("list objects are unhashable")

    def append(self, item):
        JS("""@{{self}}['__array'][@{{self}}['__array']['length']] = @{{item}};""")

    # extend in place, just in case there's somewhere a shortcut to self.__array
    def extend(self, data):
        # Transform data into an array and append to self.__array
        JS("""
        if (@{{data}} === null) {
            throw @{{TypeError}}("'NoneType' is not iterable");
        }
        if (@{{data}}['constructor'] === Array) {
        } else if (typeof @{{data}}['__iter__'] == 'function') {
            if (typeof @{{data}}['__array'] == 'object') {
                @{{data}} = @{{data}}['__array'];
            } else {
                var iter = @{{data}}['__iter__']();
                if (typeof iter['__array'] == 'object') {
                    @{{data}} = iter['__array'];
                }
                @{{data}} = [];
                var item, i = 0;
                if (typeof iter['$genfunc'] == 'function') {
                    while (typeof (item=iter['next'](true)) != 'undefined') {
                        @{{data}}[i++] = item;
                    }
                } else {
                    try {
                        while (true) {
                            @{{data}}[i++] = iter['next']();
                        }
                    }
                    catch (e) {
                        if (!@{{isinstance}}(e, @{{StopIteration}})) throw e;
                    }
                }
            }
        } else {
            throw @{{TypeError}}("'" + @{{repr}}(@{{data}}) + "' is not iterable");
        }
        var l = @{{self}}['__array'];
        var j = @{{self}}['__array']['length'];
        var n = @{{data}}['length'], i = 0;
        while (i < n) {
            l[j++] = @{{data}}[i++];
        }
        """)

    def remove(self, value):
        JS("""
        var index=@{{self}}['index'](@{{value}});
        if (index<0) {
            throw @{{ValueError}}("list['remove'](x): x not in list");
        }
        @{{self}}['__array']['splice'](index, 1);
        return true;
        """)

    def index(self, value, _start=0):
        JS("""
        var start = @{{_start}}['valueOf']();
        /* if (typeof valueXXX == 'number' || typeof valueXXX == 'string') {
            start = selfXXX['__array']['indexOf'](valueXXX, start);
            if (start >= 0)
                return start;
        } else */ {
            var len = @{{self}}['__array']['length'] >>> 0;

            start = (start < 0)
                    ? Math['ceil'](start)
                    : Math['floor'](start);
            if (start < 0)
                start += len;

            for (; start < len; start++) {
                if ( /*start in selfXXX['__array'] && */
                    @{{cmp}}(@{{self}}['__array'][start], @{{value}}) == 0)
                    return start;
            }
        }
        """)
        raise ValueError("list.index(x): x not in list")

    def insert(self, index, value):
        JS("""    var a = @{{self}}['__array']; @{{self}}['__array']=a['slice'](0, @{{index}})['concat'](@{{value}}, a['slice'](@{{index}}));""")

    def pop(self, _index = -1):
        JS("""
        var index = @{{_index}}['valueOf']();
        if (index<0) index += @{{self}}['__array']['length'];
        if (index < 0 || index >= @{{self}}['__array']['length']) {
            if (@{{self}}['__array']['length'] == 0) {
                throw @{{IndexError}}("pop from empty list");
            }
            throw @{{IndexError}}("pop index out of range");
        }
        var a = @{{self}}['__array'][index];
        @{{self}}['__array']['splice'](index, 1);
        return a;
        """)

    def __cmp__(self, l):
        if not isinstance(l, list):
            return -1
        JS("""
        var n1 = @{{self}}['__array']['length'],
            n2 = @{{l}}['__array']['length'],
            a1 = @{{self}}['__array'],
            a2 = @{{l}}['__array'],
            n, c;
        n = (n1 < n2 ? n1 : n2);
        for (var i = 0; i < n; i++) {
            c = @{{cmp}}(a1[i], a2[i]);
            if (c) return c;
        }
        if (n1 < n2) return -1;
        if (n1 > n2) return 1;
        return 0;""")

    def __getslice__(self, lower, upper):
        JS("""
        if (@{{upper}}==null)
            return @{{list}}(@{{self}}['__array']['slice'](@{{lower}}));
        return @{{list}}(@{{self}}['__array']['slice'](@{{lower}}, @{{upper}}));
        """)

    def __delslice__(self, _lower, upper):
        JS("""
        var lower = @{{_lower}};
        var n = @{{upper}} - lower;
        if (@{{upper}}==null) {
            n =  @{{self}}['__array']['length'];
        }
        if (!lower) lower = 0;
        if (n > 0) @{{self}}['__array']['splice'](lower, n);
        """)
        return None

    def __setslice__(self, lower, upper, data):
        self.__delslice__(lower, upper)
        tail = self.__getslice__(lower, None)
        self.__delslice__(lower, None)
        self.extend(data)
        self.extend(tail)
        return None

    def __getitem__(self, _index):
        JS("""
        var index = @{{_index}}['valueOf']();
        if (typeof index == 'boolean') index = @{{int}}(index);
        if (index < 0) index += @{{self}}['__array']['length'];
        if (index < 0 || index >= @{{self}}['__array']['length']) {
            throw @{{IndexError}}("list index out of range");
        }
        return @{{self}}['__array'][index];
        """)

    def __setitem__(self, _index, value):
        JS("""
        var index = @{{_index}}['valueOf']();
        if (index < 0) index += @{{self}}['__array']['length'];
        if (index < 0 || index >= @{{self}}['__array']['length']) {
            throw @{{IndexError}}("list assignment index out of range");
        }
        @{{self}}['__array'][index]=@{{value}};
        """)

    def __delitem__(self, _index):
        JS("""
        var index = @{{_index}}['valueOf']();
        if (index < 0) index += @{{self}}['__array']['length'];
        if (index < 0 || index >= @{{self}}['__array']['length']) {
            throw @{{IndexError}}("list assignment index out of range");
        }
        @{{self}}['__array']['splice'](index, 1);
        """)

    def __len__(self):
        return INT(JS("""@{{self}}['__array']['length']"""))

    def __contains__(self, value):
        try:
            self.index(value)
        except ValueError:
            return False
        return True

    def __iter__(self):
        return JS("new $iter_array(@{{self}}['__array'])")

    def __reversed__(self):
        return JS("new $reversed_iter_array(@{{self}}['__array'])")

    def __enumerate__(self):
        return JS("new $enumerate_array(@{{self}}['__array'])")

    def reverse(self):
        JS("""    @{{self}}['__array']['reverse']();""")

    def sort(self, cmp=None, key=None, reverse=False):
        if cmp is None:
            cmp = __cmp
        if key and reverse:
            def thisSort1(a,b):
                return -cmp(key(a), key(b))
            self.__array.sort(thisSort1)
        elif key:
            def thisSort2(a,b):
                return cmp(key(a), key(b))
            self.__array.sort(thisSort2)
        elif reverse:
            def thisSort3(a,b):
                return -cmp(a, b)
            self.__array.sort(thisSort3)
        else:
            self.__array.sort(cmp)

    def getArray(self):
        """
        Access the javascript Array that is used internally by this list
        """
        return self.__array

    #def __str__(self):
    #    return self.__repr__()
    #See monkey patch at the end of the list class definition

    def __repr__(self):
        if callable(self):
            return "<type '%s'>" % self.__name__
        JS("""
        var s = "[";
        for (var i=0; i < @{{self}}['__array']['length']; i++) {
            s += @{{repr}}(@{{self}}['__array'][i]);
            if (i < @{{self}}['__array']['length'] - 1)
                s += ", ";
        }
        s += "]";
        return s;
        """)

    def __add__(self, y):
        if not isinstance(y, self):
            raise TypeError("can only concatenate list to list")
        return list(self.__array.concat(y.__array))

    def __mul__(self, n):
        if not JS("@{{n}} !== null && @{{n}}['__number__'] && (@{{n}}['__number__'] != 0x01 || isFinite(@{{n}}))"):
            raise TypeError("can't multiply sequence by non-int")
        a = []
        while n:
            n -= 1
            a.extend(self.__array)
        return a

    def __rmul__(self, n):
        return self.__mul__(n)
JS("@{{list}}['__str__'] = @{{list}}['__repr__'];")
JS("@{{list}}['toString'] = @{{list}}['__str__'];")

class slice:
    def __init__(self, a1, *args):
        if args:
            self.start = a1
            self.stop = args[0]
            if len(args) > 1:
                self.step = args[1]
            else:
                self.step = None
        else:
            self.stop = a1
            self.start = None
            self.step = None

    def __cmp__(self, x):
        r = cmp(self.start, x.start)
        if r != 0:
            return r
        r = cmp(self.stop, x.stop)
        if r != 0:
            return r
        r = cmp(self.step, x.step)
        return r

    def indices(self, length):
        """
        PySlice_GetIndicesEx at ./Objects/sliceobject.c
        """
        step = 0
        start = 0
        stop = 0
        if self.step is None:
            step = 1
        else:
            step = self.step
            if step == 0:
                raise ValueError("slice step cannot be zero")

        if step < 0:
            defstart = length - 1
            defstop = -1
        else:
            defstart = 0
            defstop = length

        if self.start is None:
            start = defstart
        else:
            start = self.start
            if start < 0:
                start += length
            if start < 0:
                if step < 0:
                    start = -1
                else:
                    start = 0
            if start >= length:
                if step < 0:
                    start = length - 1
                else:
                    start = length

        if self.stop is None:
            stop = defstop
        else:
            stop = self.stop
            if stop < 0:
                stop += length
            if stop < 0:
                if step < 0:
                    stop = -1
                else:
                    stop = 0
            if stop >= length:
                if step < 0:
                    stop = length - 1
                else:
                    stop = length

        if ((step < 0 and stop >= start)
            or (step > 0 and start >= stop)):
            slicelength = 0
        elif step < 0:
            slicelength = (stop - start + 1)/step + 1;
        else:
            slicelength = (stop - start - 1)/step + 1;

        return (start, stop, step)

    def __repr__(self):
        return "slice(%s, %s, %s)" % (self.start, self.stop, self.step)

JS("@{{slice}}['__str__'] = @{{slice}}['__repr__'];")
JS("@{{slice}}['toString'] = @{{slice}}['__str__'];")

class dict:
    def __init__(self, seq=JS("[]"), **kwargs):
        self.__object = JS("{}")
        # Transform data into an array with [key,value] and add set self.__object
        # Input data can be Array(key, val), iteratable (key,val) or Object/Function
        def init(_data):
            JS("""
        var item, i, n, sKey;
        var data = @{{_data}};
        //selfXXX['__object'] = {};

        if (data === null) {
            throw @{{TypeError}}("'NoneType' is not iterable");
        }
        if (data['constructor'] === Array) {
        } else if (typeof data['__object'] == 'object') {
            data = data['__object'];
            for (sKey in data) {
                @{{self}}['__object'][sKey] = data[sKey]['slice']();
            }
            return null;
        } else if (typeof data['__iter__'] == 'function') {
            if (typeof data['__array'] == 'object') {
                data = data['__array'];
            } else {
                var iter = data['__iter__']();
                if (typeof iter['__array'] == 'object') {
                    data = iter['__array'];
                }
                data = [];
                var item, i = 0;
                if (typeof iter['$genfunc'] == 'function') {
                    while (typeof (item=iter['next'](true)) != 'undefined') {
                        data[i++] = item;
                    }
                } else {
                    try {
                        while (true) {
                            data[i++] = iter['next']();
                        }
                    }
                    catch (e) {
                        if (!@{{isinstance}}(e, @{{StopIteration}})) throw e;
                    }
                }
            }
        } else if (typeof data == 'object' || typeof data == 'function') {
            for (var key in data) {
                var _key = key;
                if (key['substring'](0,2) == '$$') {
                    // handle back mapping of name
                    // d = dict(comment='value')
                    // comment will be in the object as $$comment
                    _key = key['substring'](2);
                    if (var_remap['indexOf'](_key) < 0) {
                        _key = key;
                    }
                }
                @{{self}}['__object']['$'+_key] = [_key, data[key]];
            }
            return null;
        } else {
            throw @{{TypeError}}("'" + @{{repr}}(data) + "' is not iterable");
        }
        // Assume uniform array content...
        if ((n = data['length']) == 0) {
            return null;
        }
        i = 0;
        if (data[0]['constructor'] === Array) {
            while (i < n) {
                item = data[i++];
                key = item[0];
                sKey = (key===null?null:(typeof key['$H'] != 'undefined'?key['$H']:((typeof key=='string'||key['__number__'])?'$'+key:@{{__hash}}(key))));
                @{{self}}['__object'][sKey] = [key, item[1]];
            }
            return null;
        }
        if (typeof data[0]['__array'] != 'undefined') {
            while (i < n) {
                item = data[i++]['__array'];
                key = item[0];
                sKey = (key===null?null:(typeof key['$H'] != 'undefined'?key['$H']:((typeof key=='string'||key['__number__'])?'$'+key:@{{__hash}}(key))));
                @{{self}}['__object'][sKey] = [key, item[1]];
            }
            return null;
        }
        i = -1;
        var key;
        while (++i < n) {
            key = data[i]['__getitem__'](0);
            sKey = (key===null?null:(typeof key['$H'] != 'undefined'?key['$H']:((typeof key=='string'||key['__number__'])?'$'+key:@{{__hash}}(key))));
            @{{self}}['__object'][sKey] = [key, data[i]['__getitem__'](1)];
        }
        return null;
        """)
        init(seq)
        if kwargs:
            init(kwargs)

    def __hash__(self):
        raise TypeError("dict objects are unhashable")

    def __setitem__(self, key, value):
        JS("""
        if (typeof @{{value}} == 'undefined') {
            throw @{{ValueError}}("Value for key '" + @{{key}} + "' is undefined");
        }
        var sKey = (@{{key}}===null?null:(typeof @{{key}}['$H'] != 'undefined'?@{{key}}['$H']:((typeof @{{key}}=='string'||@{{key}}['__number__'])?'$'+@{{key}}:@{{__hash}}(@{{key}}))));
        @{{self}}['__object'][sKey] = [@{{key}}, @{{value}}];
        """)

    def __getitem__(self, key):
        JS("""
        var sKey = (@{{key}}===null?null:(typeof @{{key}}['$H'] != 'undefined'?@{{key}}['$H']:((typeof @{{key}}=='string'||@{{key}}['__number__'])?'$'+@{{key}}:@{{__hash}}(@{{key}}))));
        var value=@{{self}}['__object'][sKey];
        if (typeof value == 'undefined'){
            throw @{{KeyError}}(@{{key}});
        }
        return value[1];
        """)

    def __hash__(self):
        raise TypeError("dict objects are unhashable")

    def __nonzero__(self):
        JS("""
        for (var i in @{{self}}['__object']){
            return true;
        }
        return false;
        """)

    def __cmp__(self, other):
        if not isinstance(other, dict):
            raise TypeError("dict.__cmp__(x,y) requires y to be a 'dict'")
        JS("""
        var self_sKeys = new Array(),
            other_sKeys = new Array(),
            selfLen = 0,
            otherLen = 0,
            selfObj = @{{self}}['__object'],
            otherObj = @{{other}}['__object'];
        for (sKey in selfObj) {
           self_sKeys[selfLen++] = sKey;
        }
        for (sKey in otherObj) {
           other_sKeys[otherLen++] = sKey;
        }
        if (selfLen < otherLen) {
            return -1;
        }
        if (selfLen > otherLen) {
            return 1;
        }
        self_sKeys['sort']();
        other_sKeys['sort']();
        var c, sKey;
        for (var idx = 0; idx < selfLen; idx++) {
            c = @{{cmp}}(selfObj[sKey = self_sKeys[idx]][0], otherObj[other_sKeys[idx]][0]);
            if (c != 0) {
                return c;
            }
            c = @{{cmp}}(selfObj[sKey][1], otherObj[sKey][1]);
            if (c != 0) {
                return c;
            }
        }
        return 0;""")

    def __len__(self):
        size = 0
        JS("""
        for (var i in @{{self}}['__object']) @{{size}}++;
        """)
        return INT(size);

    #def has_key(self, key):
    #    return self.__contains__(key)
    #See monkey patch at the end of the dict class definition

    def __delitem__(self, key):
        JS("""
        var sKey = (@{{key}}===null?null:(typeof @{{key}}['$H'] != 'undefined'?@{{key}}['$H']:((typeof @{{key}}=='string'||@{{key}}['__number__'])?'$'+@{{key}}:@{{__hash}}(@{{key}}))));
        delete @{{self}}['__object'][sKey];
        """)

    def __contains__(self, key):
        JS("""
        var sKey = (@{{key}}===null?null:(typeof @{{key}}['$H'] != 'undefined'?@{{key}}['$H']:((typeof @{{key}}=='string'||@{{key}}['__number__'])?'$'+@{{key}}:@{{__hash}}(@{{key}}))));
        return typeof @{{self}}['__object'][sKey] == 'undefined' ? false : true;
        """)

    def keys(self):
        JS("""
        var keys=@{{list}}(),
            selfObj = @{{self}}['__object'],
            __array = keys['__array'],
            i = 0;
        for (var sKey in @{{self}}['__object']) {
            __array[i++] = selfObj[sKey][0];
        }
        return keys;
        """)

    @staticmethod
    def fromkeys(iterable, v = None):
        d = {}
        for i in iterable:
            d[i] = v
        return d

    def values(self):
        JS("""
        var values=@{{list}}();
        var i = 0;
        for (var key in @{{self}}['__object']) {
            values['__array'][i++] = @{{self}}['__object'][key][1];
        }
        return values;
        """)

    def items(self):
        JS("""
        var items = @{{list}}();
        var i = 0;
        for (var key in @{{self}}['__object']) {
          var kv = @{{self}}['__object'][key];
          items['__array'][i++] = @{{list}}(kv);
          }
          return items;
        """)

    def __iter__(self):
        JS("""
        var keys = new Array();
        var i = 0;
        for (var key in @{{self}}['__object']) {
            keys[i++] = @{{self}}['__object'][key][0];
        }
        return new $iter_array(keys);
""")

    def __enumerate__(self):
        JS("""
        var keys = new Array();
        var i = 0;
        for (var key in @{{self}}['__object']) {
            keys[i++] = @{{self}}['__object'][key][0];
        }
        return new $enumerate_array(keys);
""")

    #def iterkeys(self):
    #    return self.__iter__()
    #See monkey patch at the end of the dict class definition

    def itervalues(self):
        return self.values().__iter__();

    def iteritems(self):
        return self.items().__iter__();

    def setdefault(self, key, default_value):
        JS("""
        var sKey = (@{{key}}===null?null:(typeof @{{key}}['$H'] != 'undefined'?@{{key}}['$H']:((typeof @{{key}}=='string'||@{{key}}['__number__'])?'$'+@{{key}}:@{{__hash}}(@{{key}}))));
        return typeof @{{self}}['__object'][sKey] == 'undefined' ? (@{{self}}['__object'][sKey]=[@{{key}}, @{{default_value}}])[1] : @{{self}}['__object'][sKey][1];
""")

    def get(self, key, default_value=None):
        JS("""
        var empty = true;
        for (var sKey in @{{self}}['__object']) {
            empty = false;
            break;
        }
        if (empty) return @{{default_value}};
        var sKey = (@{{key}}===null?null:(typeof @{{key}}['$H'] != 'undefined'?@{{key}}['$H']:((typeof @{{key}}=='string'||@{{key}}['__number__'])?'$'+@{{key}}:@{{__hash}}(@{{key}}))));
        return typeof @{{self}}['__object'][sKey] == 'undefined' ? @{{default_value}} : @{{self}}['__object'][sKey][1];
""")

    def update(self, *args, **kwargs):
        if args:
            if len(args) > 1:
                raise TypeError("update expected at most 1 arguments, got %d" % len(args))
            d = args[0]
            if hasattr(d, "iteritems"):
                for k,v in d.iteritems():
                    self[k] = v
            elif hasattr(d, "keys"):
                for k in d:
                    self[k] = d[k]
            else:
                for k, v in d:
                    self[k] = v
        if kwargs:
            for k,v in kwargs.iteritems():
                self[k] = v

    def pop(self, k, *d):
        if len(d) > 1:
            raise TypeError("pop expected at most 2 arguments, got %s" %
                            (1 + len(d)))
        try:
            res = self[k]
            del self[k]
            return res
        except KeyError:
            if d:
                return d[0]
            else:
                raise

    def popitem(self):
        for k, v in self.iteritems():
            return (k, v)
        raise KeyError('popitem(): dictionary is empty')

    def getObject(self):
        """
        Return the javascript Object which this class uses to store
        dictionary keys and values
        """
        return self.__object

    def copy(self):
        return dict(self.items())

    def clear(self):
        self.__object = JS("{}")

    #def __str__(self):
    #    return self.__repr__()
    #See monkey patch at the end of the dict class definition

    def __repr__(self):
        if callable(self):
            return "<type '%s'>" % self.__name__
        JS("""
        var keys = new Array();
        for (var key in @{{self}}['__object'])
            keys['push'](key);

        var s = "{";
        for (var i=0; i<keys['length']; i++) {
            var v = @{{self}}['__object'][keys[i]];
            s += @{{repr}}(v[0]) + ": " + @{{repr}}(v[1]);
            if (i < keys['length']-1)
                s += ", ";
        }
        s += "}";
        return s;
        """)

    def toString(self):
        return self.__repr__()

JS("@{{dict}}['has_key'] = @{{dict}}['__contains__'];")
JS("@{{dict}}['iterkeys'] = @{{dict}}['__iter__'];")
JS("@{{dict}}['__str__'] = @{{dict}}['__repr__'];")

# __empty_dict is used in kwargs initialization
# There must me a temporary __init__ function used to prevent infinite
# recursion
def __empty_dict():
    JS("""
    var dict__init__ = @{{dict}}['__init__'];
    var d;
    @{{dict}}['__init__'] = function() {
        this['__object'] = {};
    };
    d = @{{dict}}();
    d['__init__'] = @{{dict}}['__init__'] = dict__init__;
    return d;
""")


class set(object):
    def __init__(self, _data=None):
        """ Transform data into an array with [key,value] and add set
            self.__object
            Input data can be Array(key, val), iteratable (key,val) or
            Object/Function
        """
        if _data is None:
            JS("var data = [];")
        else:
            JS("var data = @{{_data}};")

        if isSet(_data):
            JS("""
            @{{self}}['__object'] = {};
            var selfObj = @{{self}}['__object'],
                dataObj = @{{!data}}['__object'];
            for (var sVal in dataObj) {
                selfObj[sVal] = dataObj[sVal];
            }
            return null;""")
        JS("""
        var item,
            i,
            n,
            selfObj = @{{self}}['__object'] = {};

        if (@{{!data}}['constructor'] === Array) {
        // data is already an Array.
        // We deal with the Array of data after this if block.
          }

          // We may have some other set-like thing with __object
          else if (typeof @{{!data}}['__object'] == 'object') {
            var dataObj = @{{!data}}['__object'];
            for (var sKey in dataObj) {
                selfObj[sKey] = dataObj[sKey];
            }
            return null;
          }

          // Something with an __iter__ method
          else if (typeof @{{!data}}['__iter__'] == 'function') {

            // It has an __array member to iterate over. Make that our data.
            if (typeof @{{!data}}['__array'] == 'object') {
                data = @{{!data}}['__array'];
                }
            else {
                // Several ways to deal with the __iter__ method
                var iter = @{{!data}}['__iter__']();
                // iter has an __array member that's an array. Use that.
                if (typeof iter['__array'] == 'object') {
                    data = iter['__array'];
                }
                var data = [];
                var item, i = 0;
                // iter has a ['$genfunc']
                if (typeof iter['$genfunc'] == 'function') {
                    while (typeof (item=iter['next'](true)) != 'undefined') {
                        @{{!data}}[i++] = item;
                    }
                } else {
                // actually use the object's __iter__ method
                    try {
                        while (true) {
                            @{{!data}}[i++] = iter['next']();
                        }
                    }
                    catch (e) {
                        if (!@{{isinstance}}(e, @{{StopIteration}})) throw e;
                    }
                }
            }
          // Check undefined first so isIteratable can do check for __iter__.
        } else if (!(@{{isUndefined}}(@{{data}})) && @{{isIteratable}}(@{{data}}))
            {
            for (var item in @{{data}}) {
                selfObj[@{{__hash}}(item)] = item;
            }
            return null;
        } else {
            throw @{{TypeError}}("'" + @{{repr}}(@{{!data}}) + "' is not iterable");
        }
        // Assume uniform array content...
        if ((n = @{{!data}}['length']) == 0) {
            return null;
        }
        i = n-1;
        do {
            item = @{{!data}}[i];
            selfObj[@{{__hash}}(item)] = item;
        }
        while (i--);
        return null;
        """)

    def __cmp__(self, other):
        # We (mis)use cmp here for the missing __gt__/__ge__/...
        # if self == other : return 0
        # if self is subset of other: return -1
        # if self is superset of other: return 1
        # else return 2
        if not isSet(other):
            return 2
            #other = frozenset(other)
        JS("""
        var selfObj = @{{self}}['__object'],
            otherObj = @{{other}}['__object'],
            selfMismatch = false,
            otherMismatch = false;
        if (selfObj === otherObj) {
            throw @{{TypeError}}("Set operations must use two sets.");
            }
        for (var sVal in selfObj) {
            if (!(sVal in otherObj)) {
                selfMismatch = true;
                break;
            }
        }
        for (var sVal in otherObj) {
            if (!(sVal in selfObj)) {
                otherMismatch = true;
                break;
            }
        }
        if (selfMismatch && otherMismatch) return 2;
        if (selfMismatch) return 1;
        if (otherMismatch) return -1;
        return 0;
""")

    def __contains__(self, value):
        if isSet(value) == 1: # An instance of set
            # Use frozenset hash
            JS("""
            var hashes = new Array(),
                obj = @{{self}}['__object'],
                i = 0;
            for (var v in obj) {
                hashes[i++] = v;
            }
            hashes['sort']();
            var h = hashes['join']("|");
            return (h in obj);
""")
        JS("""return @{{__hash}}(@{{value}}) in @{{self}}['__object'];""")

    def __hash__(self):
        raise TypeError("set objects are unhashable")

    def __iter__(self):
        JS("""
        var items = new Array(),
            i = 0,
            obj = @{{self}}['__object'];
        for (var key in obj) {
            items[i++] = obj[key];
        }
        return new $iter_array(items);
        """)

    def __len__(self):
        size=0.0
        JS("""
        for (var i in @{{self}}['__object']) @{{size}}++;
        """)
        return INT(size)

    #def __str__(self):
    #    return self.__repr__()
    #See monkey patch at the end of the set class definition

    def __repr__(self):
        if callable(self):
            return "<type '%s'>" % self.__name__
        JS("""
        var values = new Array();
        var i = 0,
            obj = @{{self}}['__object'],
            s = @{{self}}['__name__'] + "([";
        for (var sVal in obj) {
            values[i++] = @{{repr}}(obj[sVal]);
        }
        s += values['join'](", ");
        s += "])";
        return s;
        """)

    def __and__(self, other):
        """ Return the intersection of two sets as a new set.
            only available under --number-classes
        """
        if not isSet(other):
            return NotImplemented
        return self.intersection(other)

    def __or__(self, other):
        """ Return the union of two sets as a new set..
            only available under --number-classes
        """
        if not isSet(other):
            return NotImplemented
        return self.union(other)

    def __xor__(self, other):
        """ Return the symmetric difference of two sets as a new set..
            only available under --number-classes
        """
        if not isSet(other):
            return NotImplemented
        return self.symmetric_difference(other)

    def  __sub__(self, other):
        """ Return the difference of two sets as a new Set..
            only available under --number-classes
        """
        if not isSet(other):
            return NotImplemented
        return self.difference(other)

    def add(self, value):
        JS("""@{{self}}['__object'][@{{hash}}(@{{value}})] = @{{value}};""")
        return None

    def clear(self):
        JS("""@{{self}}['__object'] = {};""")
        return None

    def copy(self):
        new_set = set()
        JS("""
        var obj = @{{new_set}}['__object'],
            selfObj = @{{self}}['__object'];
        for (var sVal in selfObj) {
            obj[sVal] = selfObj[sVal];
        }
""")
        return new_set

    def difference(self, other):
        """ Return the difference of two sets as a new set.
            (i.e. all elements that are in this set but not the other.)
        """
        if not isSet(other):
            other = frozenset(other)
        new_set = set()
        JS("""
        var obj = @{{new_set}}['__object'],
            selfObj = @{{self}}['__object'],
            otherObj = @{{other}}['__object'];
        for (var sVal in selfObj) {
            if (!(sVal in otherObj)) {
                obj[sVal] = selfObj[sVal];
            }
        }
""")
        return new_set

    def difference_update(self, other):
        """ Remove all elements of another set from this set.
        """
        if not isSet(other):
            other = frozenset(other)
        JS("""
        var selfObj = @{{self}}['__object'],
            otherObj = @{{other}}['__object'];
        for (var sVal in otherObj) {
            if (sVal in selfObj) {
                delete selfObj[sVal];
            }
        }
""")
        return None

    def discard(self, value):
        if isSet(value) == 1:
            value = frozenset(value)
        JS("""delete @{{self}}['__object'][@{{hash}}(@{{value}})];""")
        return None

    def intersection(self, other):
        """ Return the intersection of two sets as a new set.
            (i.e. all elements that are in both sets.)
        """
        if not isSet(other):
            other = frozenset(other)
        new_set = set()
        JS("""
        var obj = @{{new_set}}['__object'],
            selfObj = @{{self}}['__object'],
            otherObj = @{{other}}['__object'];
        for (var sVal in selfObj) {
            if (sVal in otherObj) {
                obj[sVal] = selfObj[sVal];
            }
        }
""")
        return new_set

    def intersection_update(self, other):
        """ Update a set with the intersection of itself and another.
        """
        if not isSet(other):
            other = frozenset(other)
        JS("""
        var selfObj = @{{self}}['__object'],
            otherObj = @{{other}}['__object'];
        for (var sVal in selfObj) {
            if (!(sVal in otherObj)) {
                delete selfObj[sVal];
            }
        }
""")
        return None

    def isdisjoint(self, other):
        """ Return True if two sets have a null intersection.
        """
        if not isSet(other):
            other = frozenset(other)
        JS("""
        var selfObj = @{{self}}['__object'],
            otherObj = @{{other}}['__object'];
        for (var sVal in selfObj) {
            if (typeof otherObj[sVal] != 'undefined') {
                return false;
            }
        }
        for (var sVal in otherObj) {
            if (typeof selfObj[sVal] != 'undefined') {
                return false;
            }
        }
""")
        return True

    def issubset(self, other):
        if not isSet(other):
            other = frozenset(other)
        return JS("@{{self}}['__cmp__'](@{{other}}) < 0")

    def issuperset(self, other):
        if not isSet(other):
            other = frozenset(other)
        return JS("(@{{self}}['__cmp__'](@{{other}})|1) == 1")

    def pop(self):
        JS("""
        for (var sVal in @{{self}}['__object']) {
            var value = @{{self}}['__object'][sVal];
            delete @{{self}}['__object'][sVal];
            return value;
        }
        """)
        raise KeyError("pop from an empty set")

    def remove(self, value):
        if isSet(value) == 1:
            val = frozenset(value)
        else:
            val = value
        JS("""
        var h = @{{hash}}(@{{val}});
        if (!(h in @{{self}}['__object'])) {
            throw @{{KeyError}}(@{{value}});
        }
        delete @{{self}}['__object'][h];
        """)

    def symmetric_difference(self, other):
        """ Return the symmetric difference of two sets as a new set.
            (i.e. all elements that are in exactly one of the sets.)
        """
        if not isSet(other):
            other = frozenset(other)
        new_set = set()
        JS("""
        var obj = @{{new_set}}['__object'],
            selfObj = @{{self}}['__object'],
            otherObj = @{{other}}['__object'];
        for (var sVal in selfObj) {
            if (typeof otherObj[sVal] == 'undefined') {
                obj[sVal] = selfObj[sVal];
            }
        }
        for (var sVal in otherObj) {
            if (typeof selfObj[sVal] == 'undefined') {
                obj[sVal] = otherObj[sVal];
            }
        }
""")
        return new_set

    def symmetric_difference_update(self, other):
        """ Update a set with the symmetric difference of itself and another.
        """
        if not isSet(other):
            other = frozenset(other)
        JS("""
        var obj = new Object(),
            selfObj = @{{self}}['__object'],
            otherObj = @{{other}}['__object'];
        for (var sVal in selfObj) {
            if (typeof otherObj[sVal] == 'undefined') {
                obj[sVal] = selfObj[sVal];
            }
        }
        for (var sVal in otherObj) {
            if (typeof selfObj[sVal] == 'undefined') {
                obj[sVal] = otherObj[sVal];
            }
        }
        @{{self}}['__object'] = obj;
""")
        return None

    def union(self, other):
        """ Return the union of two sets as a new set.
            (i.e. all elements that are in either set.)
        """
        new_set = set()
        if not isSet(other):
            other = frozenset(other)
        JS("""
        var obj = @{{new_set}}['__object'],
            selfObj = @{{self}}['__object'],
            otherObj = @{{other}}['__object'];
        for (var sVal in selfObj) {
            obj[sVal] = selfObj[sVal];
        }
        for (var sVal in otherObj) {
            if (!(sVal in selfObj)) {
                obj[sVal] = otherObj[sVal];
            }
        }
""")
        return new_set

    def update(self, data):
        if not isSet(data):
            data = frozenset(data)
        JS("""
        var selfObj = @{{self}}['__object'],
            dataObj = @{{data}}['__object'];
        for (var sVal in dataObj) {
            if (!(sVal in selfObj)) {
                selfObj[sVal] = dataObj[sVal];
            }
        }
        """)
        return None

JS("@{{set}}['__str__'] = @{{set}}['__repr__'];")
JS("@{{set}}['toString'] = @{{set}}['__repr__'];")

class frozenset(set):
    def __init__(self, _data=None):
        if JS("(!('__object' in @{{self}}))"):
            set.__init__(self, _data)

    def __hash__(self):
        JS("""
        var hashes = new Array(), obj = @{{self}}['__object'], i = 0;
        for (var v in obj) {
            hashes[i++] = v;
        }
        hashes['sort']();
        return (@{{self}}['$H'] = hashes['join']("|"));
""")

    def add(self, value):
        raise AttributeError('frozenset is immutable')

    def clear(self):
        raise AttributeError('frozenset is immutable')

    def difference_update(self, other):
        raise AttributeError('frozenset is immutable')

    def discard(self, value):
        raise AttributeError('frozenset is immutable')

    def intersection_update(self, other):
        raise AttributeError('frozenset is immutable')

    def pop(self):
        raise AttributeError('frozenset is immutable')

    def symmetric_difference_update(self, other):
        raise AttributeError('frozenset is immutable')

JS("@{{frozenset}}['__str__'] = @{{frozenset}}['__repr__'];")
JS("@{{frozenset}}['toString'] = @{{frozenset}}['__repr__'];")


class property(object):
    # From: http://users.rcn.com/python/download/Descriptor.htm
    # Extended with setter(), deleter() and fget.__doc_ copy
    def __init__(self, fget=None, fset=None, fdel=None, doc=None):
        self.fget = fget
        self.fset = fset
        self.fdel = fdel
        if not doc is None or not hasattr(fget, '__doc__') :
            self.__doc__ = doc
        else:
            self.__doc__ = fget.__doc__

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        if self.fget is None:
            raise AttributeError, "unreadable attribute"
        return self.fget(obj)

    def __set__(self, obj, value):
        if self.fset is None:
            raise AttributeError, "can't set attribute"
        self.fset(obj, value)

    def __delete__(self, obj):
        if self.fdel is None:
            raise AttributeError, "can't delete attribute"
        self.fdel(obj)

    def setter(self, fset):
        self.fset = fset
        return self

    def deleter(self, fdel):
        self.fdel = fdel
        return self


def staticmethod(func):
    JS("""
    var fnwrap = function() {
        return @{{func}}['apply'](null,$pyjs_array_slice['call'](arguments));
    };
    fnwrap['__name__'] = @{{func}}['__name__'];
    fnwrap['__args__'] = @{{func}}['__args__'];
    fnwrap['__bind_type__'] = 3;
    return fnwrap;
    """)

def super(typ, object_or_type = None):
    # This is a partial implementation: only super(type, object)
    if not _issubtype(object_or_type, typ):
        i = _issubtype(object_or_type, typ)
        raise TypeError("super(type, obj): obj must be an instance or subtype of type")
    JS("""
    var type_ = @{{typ}}
    if (typeof type_['__mro__'] == 'undefined') {
        type_ = type_['__class__'];
    }
    var fn = $pyjs_type('super', type_['__mro__']['slice'](1), {});
    fn['__new__'] = fn['__mro__'][1]['__new__'];
    fn['__init__'] = fn['__mro__'][1]['__init__'];
    if (@{{object_or_type}}['__is_instance__'] === false) {
        return fn;
    }
    var obj = new Object();
    function wrapper(obj, name) {
        var fnwrap = function() {
            return obj[name]['apply'](@{{object_or_type}},
                                   $pyjs_array_slice['call'](arguments));
        };
        fnwrap['__name__'] = name;
        fnwrap['__args__'] = obj[name]['__args__'];
        fnwrap['__bind_type__'] = obj[name]['__bind_type__'];
        return fnwrap;
    }
    for (var m in fn) {
        if (typeof fn[m] == 'function') {
            obj[m] = wrapper(fn, m);
        }
    }
    obj['__is_instance__'] = @{{object_or_type}}['__is_instance__'];
    return obj;
    """)

# taken from mochikit: range( [start,] stop[, step] )
def xrange(start, stop = None, step = 1):
    if stop is None:
        stop = start
        start = 0
    if not JS("@{{start}}!== null && @{{start}}['__number__'] && (@{{start}}['__number__'] != 0x01 || isFinite(@{{start}}))"):
        raise TypeError("xrange() integer start argument expected, got %s" % start.__class__.__name__)
    if not JS("@{{stop}}!== null && @{{stop}}['__number__'] && (@{{stop}}['__number__'] != 0x01 || isFinite(@{{stop}}))"):
        raise TypeError("xrange() integer end argument expected, got %s" % stop.__class__.__name__)
    if not JS("@{{step}}!== null && @{{step}}['__number__'] && (@{{step}}['__number__'] != 0x01 || isFinite(@{{step}}))"):
        raise TypeError("xrange() integer step argument expected, got %s" % step.__class__.__name__)
    rval = nval = start
    JS("""
    var nstep = (@{{stop}}-@{{start}})/@{{step}};
    nstep = nstep < 0 ? Math['ceil'](nstep) : Math['floor'](nstep);
    if ((@{{stop}}-@{{start}}) % @{{step}}) {
        nstep++;
    }
    var _stop = @{{start}}+ nstep * @{{step}};
    if (nstep <= 0) @{{nval}} = _stop;
    var x = {
        'next': function(noStop) {
            if (@{{nval}} == _stop) {
                if (noStop === true) {
                    return;
                }
                throw @{{StopIteration}}();
            }
            @{{rval}} = @{{nval}};
            @{{nval}} += @{{step}};
""")
    return INT(rval);
    JS("""
        },
        '$genfunc': function() {
            return this['next'](true);
        },
        '__iter__': function() {
            return this;
        },
        '__reversed__': function() {
            return @{{xrange}}(@{{!_stop}}-@{{step}}, @{{start}}-@{{step}}, -@{{step}});
        },
        'toString': function() {
            var s = "xrange(";
            if (@{{start}}!= 0) {
                s += @{{start}}+ ", ";
            }
            s += @{{!_stop}};
            if (@{{step}}!= 1) {
                s += ", " + @{{step}};
            }
            return s + ")";
        },
        '__repr__': function() {
            return "'" + this['toString']() + "'";
        }
    };
    @{{!x}}['__str__'] = @{{!x}}['toString'];
    return @{{!x}};
    """)

def get_len_of_range(lo, hi, step):
    n = 0
    JS("""
    var diff = @{{hi}} - @{{lo}} - 1;
    @{{n}} = Math['floor'](diff / @{{step}}) + 1;
    """);
    return n

def range(start, stop = None, step = 1):
    if stop is None:
        stop = start
        start = 0
    ilow = start
    if not JS("@{{start}}!== null && @{{start}}['__number__'] && (@{{start}}['__number__'] != 0x01 || isFinite(@{{start}}))"):
        raise TypeError("xrange() integer start argument expected, got %s" % start.__class__.__name__)
    if not JS("@{{stop}}!== null && @{{stop}}['__number__'] && (@{{stop}}['__number__'] != 0x01 || isFinite(@{{stop}}))"):
        raise TypeError("xrange() integer end argument expected, got %s" % stop.__class__.__name__)
    if not JS("@{{step}}!== null && @{{step}}['__number__'] && (@{{step}}['__number__'] != 0x01 || isFinite(@{{step}}))"):
        raise TypeError("xrange() integer step argument expected, got %s" % step.__class__.__name__)

    if step == 0:
        raise ValueError("range() step argument must not be zero")

    if step > 0:
        n = get_len_of_range(ilow, stop, step)
    else:
        n = get_len_of_range(stop, ilow, -step)
    r = None
    items = JS("new Array()")
    JS("""
    for (var i = 0; i < @{{n}}; i++) {
    """)
    items.push(INT(ilow))
    JS("""
        @{{ilow}} += @{{step}};
    }
    @{{r}} = @{{list}}(items);
    """)
    return r

def __getslice(object, lower, upper):
    JS("""
    if (@{{object}}=== null) {
        return null;
    }
    if (typeof @{{object}}['__getslice__'] == 'function') {
        return @{{object}}['__getslice__'](@{{lower}}, @{{upper}});
    }
    if (@{{object}}['slice'] == 'function')
        return @{{object}}['slice'](@{{lower}}, @{{upper}});

    return null;
    """)

def __delslice(object, lower, upper):
    JS("""
    if (typeof @{{object}}['__delslice__'] == 'function') {
        return @{{object}}['__delslice__'](@{{lower}}, @{{upper}});
    }
    if (@{{object}}['__getslice__'] == 'function'
      && @{{object}}['__delitem__'] == 'function') {
        if (@{{upper}}== null) {
            @{{upper}}= @{{len}}(@{{object}});
        }
        for (var i = @{{lower}}; i < @{{upper}}; i++) {
            @{{object}}['__delitem__'](i);
        }
        return null;
    }
    throw @{{TypeError}}('object does not support item deletion');
    return null;
    """)

def __setslice(object, lower, upper, value):
    JS("""
    if (typeof @{{object}}['__setslice__'] == 'function') {
        return @{{object}}['__setslice__'](@{{lower}}, @{{upper}}, @{{value}});
    }
    throw @{{TypeError}}('object does not support __setslice__');
    return null;
    """)

class str(basestring):
    def __new__(self, text=''):
        JS("""
        if (@{{text}}==='') {
            return @{{text}};
        }
        if (@{{text}}===null) {
            return 'None';
        }
        if (typeof @{{text}}=='boolean') {
            if (@{{text}}) return 'True';
            return 'False';
        }
        if (@{{text}}['__is_instance__'] === false) {
            return @{{object}}['__str__'](@{{text}});
        }
        if (@{{hasattr}}(@{{text}},'__str__')) {
            return @{{text}}['__str__']();
        }
        return String(@{{text}});
""")

def ord(x):
    if(JS("typeof @{{x}}== 'string'") and len(x) is 1):
        return INT(x.charCodeAt(0));
    else:
        JS("""throw @{{TypeError}}("ord() expected string of length 1");""")
    return None

def chr(x):
    JS("""
        return String['fromCharCode'](@{{x}});
    """)

def is_basetype(x):
    JS("""
       var t = typeof(@{{x}});
       return t == 'boolean' ||
       t == 'function' ||
       t == 'number' ||
       t == 'string' ||
       t == 'undefined';
    """)

def get_pyjs_classtype(x):
    JS("""
        if (@{{x}}!== null && typeof @{{x}}['__is_instance__'] == 'boolean') {
            var src = @{{x}}['__name__'];
            return src;
        }
        return null;
    """)

def repr(x):
    """ Return the string representation of 'x'.
    """
    # First some short cuts for speedup
    # by avoiding function calls
    JS("""
       if (@{{x}}=== null)
           return "None";

       var t = typeof(@{{x}});

       if (t == "undefined")
           return "undefined";

       if (t == "boolean") {
           if (@{{x}}) return "True";
           return "False";
       }

       if (t == "number")
           return @{{x}}['toString']();

       if (t == "string") {
           if (@{{x}}['indexOf']("'") == -1)
               return "'" + @{{x}}+ "'";
           if (@{{x}}['indexOf']('"') == -1)
               return '"' + @{{x}}+ '"';
           var s = @{{x}}['$$replace'](new RegExp('"', "g"), '\\\\"');
           return '"' + s + '"';
       }

""")
    if hasattr(x, '__repr__'):
        if callable(x):
            return x.__repr__(x)
        return x.__repr__()
    JS("""
       if (t == "function")
           return "<function " + @{{x}}['toString']() + ">";

       // If we get here, x is an object.  See if it's a Pyjamas class.

       if (!@{{hasattr}}(@{{x}}, "__init__"))
           return "<" + @{{x}}['toString']() + ">";

       // Handle the common Pyjamas data types.

       var constructor = "UNKNOWN";

       constructor = @{{get_pyjs_classtype}}(@{{x}});

        //alert("repr constructor: " + constructor);

       // If we get here, the class isn't one we know -> return the class name.
       // Note that we replace underscores with dots so that the name will
       // (hopefully!) look like the original Python name.
       // (XXX this was for pyjamas 0['4'] but may come back in an optimised mode)

       //var s = constructor['$$replace'](new RegExp('_', "g"), '.');
       return "<" + constructor + " object>";
    """)

def len(object):
    v = 0
    JS("""
    if (typeof @{{object}}== 'undefined') {
        throw @{{UndefinedValueError}}("obj");
    }
    if (@{{object}}=== null)
        return @{{v}};
    else if (typeof @{{object}}['__array'] != 'undefined')
        @{{v}} = @{{object}}['__array']['length'];
    else if (typeof @{{object}}['__len__'] == 'function')
        @{{v}} = @{{object}}['__len__']();
    else if (typeof @{{object}}['length'] != 'undefined')
        @{{v}} = @{{object}}['length'];
    else throw @{{TypeError}}("object has no len()");
    if (@{{v}}['__number__'] & 0x06) return @{{v}};
    """)
    return INT(v)

def isinstance(object_, classinfo):
    JS("""
    if (typeof @{{object_}}== 'undefined') {
        return false;
    }
    if (@{{object_}}== null) {
        if (@{{classinfo}}== null) {
            return true;
        }
        return false;
    }
    switch (@{{classinfo}}['__name__']) {
        case 'float':
            return typeof @{{object_}}== 'number' && @{{object_}}['__number__'] == 0x01 && isFinite(@{{object_}});
        case 'int':
        case 'float_int':
            if (@{{object_}}!== null
                && @{{object_}}['__number__']) {
                if (@{{object_}}['__number__'] == 0x02) {
                    return true;
                }
                if (isFinite(@{{object_}}) &&
                    Math['ceil'](@{{object_}}) == @{{object_}}) {
                    return true;
                }
            }
            return false;
        case 'basestring':
        case 'str':
            return typeof @{{object_}}== 'string';
        case 'bool':
            return typeof @{{object_}}== 'boolean';
        case 'long':
            return @{{object_}}['__number__'] == 0x04;
    }
    if (typeof @{{object_}}!= 'object' && typeof @{{object_}}!= 'function') {
        return false;
    }
""")
    if _isinstance(classinfo, tuple):
        if _isinstance(object_, tuple):
            return True
        for ci in classinfo:
            if isinstance(object_, ci):
                return True
        return False
    else:
        return _isinstance(object_, classinfo)

def _isinstance(object_, classinfo):
    JS("""
    if (   @{{object_}}['__is_instance__'] !== true
        || @{{classinfo}}['__is_instance__'] === null) {
        return false;
    }
    var __mro__ = @{{object_}}['__mro__'];
    var n = __mro__['length'];
    if (@{{classinfo}}['__is_instance__'] === false) {
        while (--n >= 0) {
            if (@{{object_}}['__mro__'][n] === @{{classinfo}}['prototype']) {
                return true;
            }
        }
        return false;
    }
    while (--n >= 0) {
        if (@{{object_}}['__mro__'][n] === @{{classinfo}}['__class__']) return true;
    }
    return false;
    """)

def issubclass(class_, classinfo):
    if JS(""" typeof @{{class_}} == 'undefined' || @{{class_}} === null || @{{class_}}['__is_instance__'] !== false """):
        raise TypeError("arg 1 must be a class")

    if isinstance(classinfo, tuple):
        for ci in classinfo:
            if issubclass(class_, ci):
                return True
        return False
    else:
        if JS(""" typeof @{{classinfo}} == 'undefined' || @{{classinfo}}['__is_instance__'] !== false """):
            raise TypeError("arg 2 must be a class or tuple of classes")
        return _issubtype(class_, classinfo)

def _issubtype(object_, classinfo):
    JS("""
    if (   @{{object_}}['__is_instance__'] === null
        || @{{classinfo}}['__is_instance__'] === null) {
        return false;
    }
    var __mro__ = @{{object_}}['__mro__'];
    var n = __mro__['length'];
    if (@{{classinfo}}['__is_instance__'] === false) {
        while (--n >= 0) {
            if (@{{object_}}['__mro__'][n] === @{{classinfo}}['prototype']) {
                return true;
            }
        }
        return false;
    }
    while (--n >= 0) {
        if (@{{object_}}['__mro__'][n] === @{{classinfo}}['__class__']) return true;
    }
    return false;
    """)

def __getattr_check(attr, attr_left, attr_right, attrstr,
                bound_methods, descriptors,
                attribute_checking, source_tracking):
    """
       (function(){
            var $pyjs__testval;
            var v, vl; /* hmm.... */
            if (bound_methods || descriptors) {
                pyjs__testval = (v=(vl=attr_left)[attr_right]) == null ||
                                ((vl.__is_instance__) &&
                                 typeof v == 'function');
                if (descriptors) {
                    pyjs_testval = pyjs_testval ||
                            (typeof v['__get__'] == 'function');
                }
                pyjs__testval = (pyjs__testval ?
                    @{{getattr}}(vl, attr_right):
                    attr);
            } else {
                pyjs__testval = attr;
            }
            return (typeof $pyjs__testval=='undefined'?
                (function(){throw TypeError(attrstr + " is undefined");})():
                $pyjs__testval);
       )();
    """
    pass

def getattr(obj, name, default_value=None):
    JS("""
    if (@{{obj}}=== null || typeof @{{obj}}== 'undefined') {
        if (arguments['length'] != 3 || typeof @{{obj}}== 'undefined') {
            throw @{{AttributeError}}("'" + @{{repr}}(@{{obj}}) + "' has no attribute '" + @{{name}}+ "'");
        }
        return @{{default_value}};
    }
    var mapped_name = attrib_remap['indexOf'](@{{name}}) < 0 ? @{{name}}:
                        '$$'+@{{name}};
    if (typeof @{{obj}}[mapped_name] == 'undefined') {
        if (arguments['length'] != 3) {
            if (@{{obj}}['__is_instance__'] === true &&
                    typeof @{{obj}}['__getattr__'] == 'function') {
                return @{{obj}}['__getattr__'](@{{name}});
            }
            throw @{{AttributeError}}("'" + @{{repr}}(@{{obj}}) + "' has no attribute '" + @{{name}}+ "'");
        }
        return @{{default_value}};
    }
    var method = @{{obj}}[mapped_name];
    if (method === null) return method;

    if (typeof method['__get__'] == 'function') {
        if (@{{obj}}['__is_instance__']) {
            return method['__get__'](@{{obj}}, @{{obj}}['__class__']);
        }
        return method['__get__'](null, @{{obj}}['__class__']);
    }
    if (   typeof method != 'function'
        || typeof method['__is_instance__'] != 'undefined'
        || @{{obj}}['__is_instance__'] !== true
        || @{{name}}== '__class__') {
        return @{{obj}}[mapped_name];
    }

    var fnwrap = function() {
        return method['apply'](@{{obj}},$pyjs_array_slice['call'](arguments));
    };
    fnwrap['__name__'] = @{{name}};
    fnwrap['__args__'] = @{{obj}}[mapped_name]['__args__'];
    fnwrap['__class__'] = @{{obj}}['__class__'];
    fnwrap['__doc__'] = method['__doc__'] || '';
    fnwrap['__bind_type__'] = @{{obj}}[mapped_name]['__bind_type__'];
    if (typeof @{{obj}}[mapped_name]['__is_instance__'] != 'undefined') {
        fnwrap['__is_instance__'] = @{{obj}}[mapped_name]['__is_instance__'];
    } else {
        fnwrap['__is_instance__'] = false;
    }
    return fnwrap;
    """)

def _del(obj):
    JS("""
    if (typeof @{{obj}}['__delete__'] == 'function') {
        @{{obj}}['__delete__'](@{{obj}});
    } else {
        delete @{{obj}};
    }
    """)

def delattr(obj, name):
    JS("""
    if (typeof @{{obj}}== 'undefined') {
        throw @{{UndefinedValueError}}("obj");
    }
    if (typeof @{{name}}!= 'string') {
        throw @{{TypeError}}("attribute name must be string");
    }
    if (@{{obj}}['__is_instance__'] && typeof @{{obj}}['__delattr__'] == 'function') {
        @{{obj}}['__delattr__'](@{{name}});
        return;
    }
    var mapped_name = attrib_remap['indexOf'](@{{name}}) < 0 ? @{{name}}:
                        '$$'+@{{name}};
    if (   @{{obj}}!== null
        && (typeof @{{obj}}== 'object' || typeof @{{obj}}== 'function')
        && (typeof(@{{obj}}[mapped_name]) != "undefined") ){
        if (@{{obj}}['__is_instance__']
            && typeof @{{obj}}[mapped_name]['__delete__'] == 'function') {
            @{{obj}}[mapped_name]['__delete__'](@{{obj}});
        } else {
            delete @{{obj}}[mapped_name];
        }
        return;
    }
    if (@{{obj}}=== null) {
        throw @{{AttributeError}}("'NoneType' object"+
                                  "has no attribute '"+@{{name}}+"'");
    }
    if (typeof @{{obj}}!= 'object' && typeof @{{obj}}== 'function') {
       throw @{{AttributeError}}("'"+typeof(@{{obj}})+
                                 "' object has no attribute '"+@{{name}}+"'");
    }
    throw @{{AttributeError}}(@{{obj}}['__name__']+
                              " instance has no attribute '"+ @{{name}}+"'");
    """)

def setattr(obj, name, value):
    JS("""
    if (typeof @{{obj}}== 'undefined') {
        throw @{{UndefinedValueError}}("obj");
    }
    if (typeof @{{name}}!= 'string') {
        throw @{{TypeError}}("attribute name must be string");
    }
    if (@{{obj}}['__is_instance__'] && typeof @{{obj}}['__setattr__'] == 'function') {
        @{{obj}}['__setattr__'](@{{name}}, @{{value}})
        return;
    }
    if (attrib_remap['indexOf'](@{{name}}) >= 0) {
        @{{name}}= '$$' + @{{name}};
    }
    if (   typeof @{{obj}}[@{{name}}] != 'undefined'
        && @{{obj}}['__is_instance__']
        && @{{obj}}[@{{name}}] !== null
        && typeof @{{obj}}[@{{name}}]['__set__'] == 'function') {
        @{{obj}}[@{{name}}]['__set__'](@{{obj}}, @{{value}});
    } else {
        @{{obj}}[@{{name}}] = @{{value}};
    }
    """)

def hasattr(obj, name):
    JS("""
    if (typeof @{{obj}}== 'undefined') {
        throw @{{UndefinedValueError}}("obj");
    }
    if (typeof @{{name}} != 'string') {
        throw @{{TypeError}}("attribute name must be string");
    }
    if (@{{obj}}=== null) return false;
    if (typeof @{{obj}}[@{{name}}] == 'undefined' && (
            typeof @{{obj}}['$$'+@{{name}}] == 'undefined' ||
            attrib_remap['indexOf'](@{{name}}) < 0)
      ) {
        return false;
    }
    //if (@{{obj}}!= 'object' && typeof @{{obj}}!= 'function')
    //    return false;
    return true;
    """)

def dir(obj):
    JS("""
    if (typeof @{{obj}}== 'undefined') {
        throw @{{UndefinedValueError}}("obj");
    }
    var properties=@{{list}}();
    for (var property in @{{obj}}) {
        if (property['substring'](0,2) == '$$') {
            // handle back mapping of name
            properties['append'](property['substring'](2));
        } else if (attrib_remap['indexOf'](property) < 0) {
            properties['append'](property);
        }
    }
    return properties;
    """)

def filter(obj, method, sequence=None):
    # object context is LOST when a method is passed, hence object must be passed separately
    # to emulate python behaviour, should generate this code inline rather than as a function call
    items = []
    if sequence is None:
        sequence = method
        method = obj

        for item in sequence:
            if method(item):
                items.append(item)
    else:
        for item in sequence:
            if method.call(obj, item):
                items.append(item)

    return items


def map(obj, method, sequence=None):
    items = []

    if sequence is None:
        sequence = method
        method = obj

        for item in sequence:
            items.append(method(item))
    else:
        for item in sequence:
            items.append(method.call(obj, item))

    return items


def reduce(func, iterable, initializer=JS("(function(){return;})()")):
    try:
        iterable = iter(iterable)
    except:
        raise TypeError, "reduce() arg 2 must support iteration"
    emtpy = True
    for value in iterable:
        emtpy = False
        if JS("typeof @{{initializer}}== 'undefined'"):
            initializer = value
        else:
            initializer = func(initializer, value)
    if empty:
        if JS("typeof @{{initializer}}== 'undefined'"):
            raise TypeError, "reduce() of empty sequence with no initial value"
        return initializer
    return initializer


def zip(*iterables):
    n = len(iterables)
    if n == 0:
        return []
    lst = []
    iterables = [iter(i) for i in iterables]
    try:
        while True:
            t = []
            i = 0
            while i < n:
                t.append(iterables[i].next())
                i += 1
            lst.append(tuple(t))
    except StopIteration:
        pass
    return lst


def sorted(iterable, cmp=None, key=None, reverse=False):
    lst = list(iterable)
    lst.sort(cmp, key, reverse)
    return lst


def reversed(iterable):
    if hasattr(iterable, '__reversed__'):
        return iterable.__reversed__()
    if hasattr(iterable, '__len__') and hasattr(iterable, '__getitem__'):
        if len(iterable) == 0:
            l = []
            return l.__iter__()
        try:
            v = iterable[0]
            return _reversed(iterable)
        except:
            pass
    raise TypeError("argument to reversed() must be a sequence")

def _reversed(iterable):
    i = len(iterable)
    while i > 0:
        i -= 1
        yield iterable[i]

def enumerate(seq):
    JS("""
    if (typeof @{{seq}}['__enumerate__'] == 'function') {
        return @{{seq}}['__enumerate__']();
    }
""")
    return _enumerate(seq)

def _enumerate(sequence):
    nextIndex = 0
    for item in sequence:
        yield (nextIndex, item)
        nextIndex += 1

def iter(iterable, sentinel=None):
    if sentinel is None:
        if isIteratable(iterable):
            return iterable.__iter__()
        if hasattr(iterable, '__getitem__'):
            return _iter_getitem(iterable)
        raise TypeError("object is not iterable")
    if isFunction(iterable):
        return _iter_callable(iterable, sentinel)
    raise TypeError("iter(v, w): v must be callable")

def _iter_getitem(object):
    i = 0
    try:
        while True:
            yield object[i]
            i += 1
    except IndexError:
        pass

def _iter_callable(callable, sentinel):
    while True:
        nextval = callable()
        if nextval == sentinel:
            break
        yield nextval

def min(*sequence):
    if len(sequence) == 1:
        sequence = sequence[0]
    minValue = None
    for item in sequence:
        if minValue is None:
            minValue = item
        elif cmp(item, minValue) == -1:
            minValue = item
    return minValue


def max(*sequence):
    if len(sequence) == 1:
        sequence = sequence[0]
    maxValue = None
    for item in sequence:
        if maxValue is None:
            maxValue = item
        elif cmp(item, maxValue) == 1:
            maxValue = item
    return maxValue

def sum(iterable, start=None):
    if start is None:
        start = 0
    for i in iterable:
        start += i
    return start

class complex:
    def __init__(self, real, imag):
        self.real = float(real)
        self.imag = float(imag)

    def __repr__(self):
        if self.real:
            return "(%s+%sj)" % (self.real, self.imag)
        else:
            return "%sj" % self.imag

    def __add__(self, b):
        if isinstance(b, complex):
            return complex(self.real + b.real, self.imag + b.imag)
        elif JS("typeof @{{b}}['__number__'] != 'undefined'"):
            return complex(self.real + b, self.imag)
        else:
            raise TypeError("unsupported operand type(s) for +: '%r', '%r'" % (self, b))

JS("@{{complex}}['__radd__'] = @{{complex}}['__add__'];")
JS("@{{complex}}['__str__'] = @{{complex}}['__repr__'];")
JS("@{{complex}}['toString'] = @{{complex}}['__repr__'];")

JS("@{{next_hash_id}} = 0;")

# hash(obj) == (obj === null? null : (typeof obj.$H != 'undefined' ? obj.$H : ((typeof obj == 'string' || obj.__number__) ? '$'+obj : @{{__hash}}(obj))))
if JS("typeof 'a'[0] == 'undefined'"):
    # IE: cannot do "abc"[idx]
    # IE has problems with setting obj.$H on certain DOM objects
    #def __hash(obj):
    JS("""@{{__hash}} = function(obj) {
        switch (obj['constructor']) {
            case String:
            case Number:
            case Date:
                return '$'+obj;
        }
        if (typeof obj['__hash__'] == 'function') return obj['__hash__']();
        if (typeof obj['nodeType'] != 'number') {
            try {
            obj['$H'] = ++@{{next_hash_id}};
            } catch (e) {
                return obj;
            }
            return @{{next_hash_id}};
            return obj['$H'] = ++@{{next_hash_id}};
        }
        if (typeof obj['setAttribute'] == 'undefined') {
            return obj;
        }
        var $H;
        if ($H = obj['getAttribute']('$H')) {
            return $H;
        }
        obj['setAttribute']('$H', ++@{{next_hash_id}});
        return @{{next_hash_id}};
    };
        """)

    #def hash(obj):
    JS("""@{{hash}} = function(obj) {
        if (obj === null) return null;

        if (typeof obj['$H'] != 'undefined') return obj['$H'];
        if (typeof obj == 'string' || obj['__number__']) return '$'+obj;
        switch (obj['constructor']) {
            case String:
            case Number:
            case Date:
                return '$'+obj;
        }
        if (typeof obj['__hash__'] == 'function') return obj['__hash__']();
        if (typeof obj['nodeType'] != 'number') {
            try {
            obj['$H'] = ++@{{next_hash_id}};
            } catch (e) {
                return obj;
            }
            return @{{next_hash_id}};
            return obj['$H'] = ++@{{next_hash_id}};
        }
        if (typeof obj['setAttribute'] == 'undefined') {
            return obj;
        }
        var $H;
        if ($H = obj['getAttribute']('$H')) {
            return $H;
        }
        obj['setAttribute']('$H', ++@{{next_hash_id}});
        return @{{next_hash_id}};
    };
        """)
else:
    #def __hash(obj):
    JS("""@{{__hash}} = function(obj) {
        switch (obj['constructor']) {
            case String:
            case Number:
            case Date:
                return '$'+obj;
        }
        if (typeof obj['__hash__'] == 'function') return obj['__hash__']();
        obj['$H'] = ++@{{next_hash_id}};
        return obj['$H'];
    };
        """)

   #def hash(obj):
    JS("""@{{hash}} = function(obj) {
        if (obj === null) return null;

        if (typeof obj['$H'] != 'undefined') return obj['$H'];
        if (typeof obj == 'string' || obj['__number__']) return '$'+obj;
        switch (obj['constructor']) {
            case String:
            case Number:
            case Date:
                return '$'+obj;
        }
        if (typeof obj['__hash__'] == 'function') return obj['__hash__']();
        obj['$H'] = ++@{{next_hash_id}};
        return obj['$H'];
    };
        """)


# type functions from Douglas Crockford's Remedial Javascript: http://www.crockford.com/javascript/remedial.html
def isObject(a):
    JS("""
    return (@{{a}}!== null && (typeof @{{a}}== 'object')) || typeof @{{a}}== 'function';
    """)

def isFunction(a):
    JS("""
    return typeof @{{a}}== 'function';
    """)

callable = isFunction

def isString(a):
    JS("""
    return typeof @{{a}}== 'string';
    """)

def isNull(a):
    JS("""
    return typeof @{{a}}== 'object' && !@{{a}};
    """)

def isArray(a):
    JS("""
    return @{{isObject}}(@{{a}}) && @{{a}}['constructor'] === Array;
    """)

def isUndefined(a):
    JS("""
    return typeof @{{a}}== 'undefined';
    """)

def isIteratable(a):
    JS("""
    if (@{{a}}=== null) return false;
    return typeof @{{a}}['__iter__'] == 'function';
    """)

def isNumber(a):
    JS("""
    return @{{a}}!== null && @{{a}}['__number__'] &&
           (@{{a}}['__number__'] != 0x01 || isFinite(@{{a}}));
    """)

def isInteger(a):
    JS("""
    switch (@{{a}}['__number__']) {
        case 0x01:
            if (@{{a}} != Math['floor'](@{{a}})) break;
        case 0x02:
        case 0x04:
            return true;
    }
    return false;
""")

def isSet(a):
    JS("""
    if (@{{a}}=== null) return false;
    if (typeof @{{a}}['__object'] == 'undefined') return false;
    var a_mro = @{{a}}['__mro__'];
    switch (a_mro[a_mro['length']-2]['__md5__']) {
        case @{{set}}['__md5__']:
            return 1;
        case @{{frozenset}}['__md5__']:
            return 2;
    }
    return false;
""")
def toJSObjects(x):
    """
       Convert the pyjs pythonic list and dict objects into javascript Object and Array
       objects, recursively.
    """
    if isArray(x):
        JS("""
        var result = [];
        for(var k=0; k < @{{x}}['length']; k++) {
           var v = @{{x}}[k];
           var tv = @{{toJSObjects}}(v);
           result['push'](tv);
        }
        return result;
        """)
    if isObject(x):
        if getattr(x, '__number__', None):
            return x.valueOf()
        elif isinstance(x, dict):
            JS("""
            var o = @{{x}}['getObject']();
            var result = {};
            for (var i in o) {
               result[o[i][0]['toString']()] = @{{toJSObjects}}(o[i][1]);
            }
            return result;
            """)
        elif isinstance(x, list):
            return toJSObjects(x.__array)
        elif hasattr(x, '__class__'):
            # we do not have a special implementation for custom
            # classes, just pass it on
            return x
        elif isFunction(x):
            return x
    if isObject(x):
        JS("""
        var result = {};
        for(var k in @{{x}}) {
            var v = @{{x}}[k];
            var tv = @{{toJSObjects}}(v);
            result[k] = tv;
            }
            return result;
         """)
    if isString(x):
        return str(x)
    return x

def sprintf(strng, args):
    # See http://docs.python.org/library/stdtypes.html
    JS(r"""
    var re_dict = /([^%]*)%[(]([^)]+)[)]([#0\x20\x2B-]*)(\d+)?(\.\d+)?[hlL]?(.)((.|\n)*)/;
    var re_list = /([^%]*)%([#0\x20\x2B-]*)(\*|(\d+))?(\.\d+)?[hlL]?(.)((.|\n)*)/;
    var re_exp = /(.*)([+-])(.*)/;

    var argidx = 0;
    var nargs = 0;
    var result = [];
    var remainder = @{{strng}};

    function formatarg(flags, minlen, precision, conversion, param) {
        var subst = '';
        var numeric = true;
        var left_padding = 1;
        var padchar = ' ';
        if (minlen === null || minlen == 0 || !minlen) {
            minlen=0;
        } else {
            minlen = parseInt(minlen);
        }
        if (!precision) {
            precision = null;
        } else {
            precision = parseInt(precision['substr'](1));
        }
        if (flags['indexOf']('-') >= 0) {
            left_padding = 0;
        }
        switch (conversion) {
            case '%':
                numeric = false;
                subst = '%';
                break;
            case 'c':
                numeric = false;
                subst = String['fromCharCode'](parseInt(param));
                break;
            case 'd':
            case 'i':
            case 'u':
                subst = '' + parseInt(param);
                break;
            case 'e':
                if (precision === null) {
                    precision = 6;
                }
                subst = re_exp['exec'](String(param['toExponential'](precision)));
                if (subst[3]['length'] == 1) {
                    subst = subst[1] + subst[2] + '0' + subst[3];
                } else {
                    subst = subst[1] + subst[2] + subst[3];
                }
                break;
            case 'E':
                if (precision === null) {
                    precision = 6;
                }
                subst = re_exp['exec'](String(param['toExponential'](precision))['toUpperCase']());
                if (subst[3]['length'] == 1) {
                    subst = subst[1] + subst[2] + '0' + subst[3];
                } else {
                    subst = subst[1] + subst[2] + subst[3];
                }
                break;
            case 'f':
                if (precision === null) {
                    precision = 6;
                }
                subst = String(parseFloat(param)['toFixed'](precision));
                break;
            case 'F':
                if (precision === null) {
                    precision = 6;
                }
                subst = String(parseFloat(param)['toFixed'](precision))['toUpperCase']();
                break;
            case 'g':
                // FIXME: Issue 672 should return double digit exponent
                // probably can remove code in formatd after that
                if (precision === null && flags['indexOf']('#') >= 0) {
                    precision = 6;
                }
                if (param >= 1E6 || param < 1E-5) {
                    subst = String(precision == null ? param['toExponential']() : param['toExponential']()['toPrecision'](precision));
                } else {
                    subst = String(precision == null ? parseFloat(param) : parseFloat(param)['toPrecision'](precision));
                }
                break;
            case 'G':
                if (precision === null && flags['indexOf']('#') >= 0) {
                    precision = 6;
                }
                if (param >= 1E6 || param < 1E-5) {
                    subst = String(precision == null ? param['toExponential']() : param['toExponential']()['toPrecision'](precision))['toUpperCase']();
                } else {
                    subst = String(precision == null ? parseFloat(param) : parseFloat(param)['toPrecision'](precision))['toUpperCase']()['toUpperCase']();
                }
                break;
            case 'r':
                numeric = false;
                subst = @{{repr}}(param);
                break;
            case 's':
                numeric = false;
                subst = @{{str}}(param);
                break;
            case 'o':
                param = @{{int}}(param);
                subst = param['toString'](8);
                if (subst != '0' && flags['indexOf']('#') >= 0) {
                    subst = '0' + subst;
                }
                break;
            case 'x':
                param = @{{int}}(param);
                subst = param['toString'](16);
                if (flags['indexOf']('#') >= 0) {
                    if (left_padding) {
                        subst = subst['rjust'](minlen - 2, '0');
                    }
                    subst = '0x' + subst;
                }
                break;
            case 'X':
                param = @{{int}}(param);
                subst = param['toString'](16)['toUpperCase']();
                if (flags['indexOf']('#') >= 0) {
                    if (left_padding) {
                        subst = subst['rjust'](minlen - 2, '0');
                    }
                    subst = '0x' + subst;
                }
                break;
            default:
                throw @{{ValueError}}("unsupported format character '" + conversion + "' ("+@{{hex}}(conversion['charCodeAt'](0))+") at index " + (@{{strng}}['length'] - remainder['length'] - 1));
        }
        if (minlen && subst['length'] < minlen) {
            if (numeric && left_padding && flags['indexOf']('0') >= 0) {
                padchar = '0';
            }
            subst = left_padding ? subst['rjust'](minlen, padchar) : subst['ljust'](minlen, padchar);
        }
        return subst;
    }

    function sprintf_list(strng, args) {
        var a, left, flags, precision, conversion, minlen, param,
            __array = result;
        while (remainder) {
            a = re_list['exec'](remainder);
            if (a === null) {
                __array[__array['length']] = remainder;
                break;
            }
            left = a[1]; flags = a[2];
            minlen = a[3]; precision = a[5]; conversion = a[6];
            remainder = a[7];
            if (typeof minlen == 'undefined') minlen = null;
            if (typeof precision == 'undefined') precision = null;
            if (typeof conversion == 'undefined') conversion = null;
            __array[__array['length']] = left;
            if (minlen == '*') {
                if (argidx == nargs) {
                    throw @{{TypeError}}("not enough arguments for format string");
                }
                minlen = args['__getitem__'](argidx++);
                switch (minlen['__number__']) {
                    case 0x02:
                    case 0x04:
                        break;
                    case 0x01:
                        if (minlen == Math['floor'](minlen)) {
                            break;
                        }
                    default:
                        throw @{{TypeError}}('* wants int');
                }
            }
            if (conversion != '%') {
                if (argidx == nargs) {
                    throw @{{TypeError}}("not enough arguments for format string");
                }
                param = args['__getitem__'](argidx++);
            }
            __array[__array['length']] = formatarg(flags, minlen, precision, conversion, param);
        }
    }

    function sprintf_dict(strng, args) {
        var a = null,
            left = null,
            flags = null,
            precision = null,
            conversion = null,
            minlen = null,
            minlen_type = null,
            key = null,
            arg = args,
            param,
            __array = result;

        argidx++;
        while (remainder) {
            a = re_dict['exec'](remainder);
            if (a === null) {
                __array[__array['length']] = remainder;
                break;
            }
            left = a[1]; key = a[2]; flags = a[3];
            minlen = a[4]; precision = a[5]; conversion = a[6];
            remainder = a[7];
            if (typeof minlen == 'undefined') minlen = null;
            if (typeof precision == 'undefined') precision = null;
            if (typeof conversion == 'undefined') conversion = null;
            __array[__array['length']] = left;
            param = arg['__getitem__'](key);
            __array[__array['length']] = formatarg(flags, minlen, precision, conversion, param);
        }
    }

    var constructor = args === null ? 'NoneType' : (args['__md5__'] == @{{tuple}}['__md5__'] ? 'tuple': (args['__md5__'] == @{{dict}}['__md5__'] ? 'dict': 'Other'));
    if (strng['indexOf']("%(") >= 0) {
        if (re_dict['exec'](strng) !== null) {
            if (constructor != "dict") {
                throw @{{TypeError}}("format requires a mapping");
            }
            sprintf_dict(strng, args);
            return result['join']("");
        }
    }
    if (constructor != "tuple") {
        args = @{{tuple}}([args]);
    }
    nargs = args['__array']['length'];
    sprintf_list(strng, args);
    if (argidx != nargs) {
        throw @{{TypeError}}('not all arguments converted during string formatting');
    }
    return result['join']("");
""")

__module_internals = set(['__track_lines__'])
def _globals(module):
    """
    XXX: It should return dictproxy instead!
    """
    d = dict()
    for name in dir(module):
        if not name in __module_internals:
            d[name] = JS("@{{module}}[@{{name}}]")
    return d

def debugReport(msg):
    JS("""
    @{{printFunc}}([@{{msg}}], true);
    """)

JS("""
var $printFunc = null;
if (   typeof $wnd['console'] != 'undefined'
    && typeof $wnd['console']['debug'] == 'function') {
    $printFunc = function(s) {
        $wnd['console']['debug'](s);
    };
} else if (   typeof $wnd['opera'] != 'undefined'
           && typeof $wnd['opera']['postError'] == 'function') {
    $printFunc = function(s) {
        $wnd['opera']['postError'](s);
    };
} else if ( typeof console != 'undefined') {
    if (   typeof console['log'] == 'function'
        || typeof console['log'] == 'object') {
        $printFunc = function(s){
            console['log'](s);
        };
    }
}
""")

def _print_to_console(s):
    JS("""
    if ($printFunc === null) return null;
    $printFunc(@{{s}});
    """)

def printFunc(objs, newline):
    JS("""
    var s = "";
    for(var i=0; i < @{{objs}}['length']; i++) {
        if(s != "") s += " ";
        s += @{{objs}}[i];
    }
    if (newline) {
      s += '\\n';
    }
    @{{sys}}['stdout']['write'](s);
    """)

def pow(x, y, z = None):
    p = None
    JS("@{{p}} = Math['pow'](@{{x}}, @{{y}});")
    if z is None:
        return float(p)
    return float(p % z)

def hex(x):
    JS("""
    if (typeof @{{x}} == 'number') {
        if (Math['floor'](@{{x}}) == @{{x}}) {
            return '0x' + @{{x}}['toString'](16);
        }
    } else {
        switch (@{{x}}['__number__']) {
            case 0x02:
                return '0x' + @{{x}}['__v']['toString'](16);
            case 0x04:
                return @{{x}}['__hex__']();
        }
    }
""")
    raise TypeError("hex() argument can't be converted to hex")

def oct(x):
    JS("""
    if (typeof @{{x}} == 'number') {
        if (Math['floor'](@{{x}}) == @{{x}}) {
            return @{{x}} == 0 ? '0': '0' + @{{x}}['toString'](8);
        }
    } else {
        switch (@{{x}}['__number__']) {
            case 0x02:
                return @{{x}}['__v'] == 0 ? '0': '0' + @{{x}}['__v']['toString'](8);
            case 0x04:
                return @{{x}}['__oct__']();
        }
    }
""")
    raise TypeError("oct() argument can't be converted to oct")

def round(x, n = 0):
    n = pow(10, n)
    r = None
    JS("@{{r}} = Math['round'](@{{n}}*@{{x}})/@{{n}};")
    return float(r)

def divmod(x, y):
    JS("""
    if (@{{x}} !== null && @{{y}} !== null) {
        switch ((@{{x}}['__number__'] << 8) | @{{y}}['__number__']) {
            case 0x0101:
            case 0x0104:
            case 0x0401:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                var f = Math['floor'](@{{x}} / @{{y}});
                return @{{tuple}}([f, @{{x}} - f * @{{y}}]);
            case 0x0102:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('float divmod()');
                var f = Math['floor'](@{{x}} / @{{y}}['__v']);
                return @{{tuple}}([f, @{{x}} - f * @{{y}}['__v']]);
            case 0x0201:
                if (@{{y}} == 0) throw @{{ZeroDivisionError}}('float divmod()');
                var f = Math['floor'](@{{x}}['__v'] / @{{y}});
                return @{{tuple}}([f, @{{x}}['__v'] - f * @{{y}}]);
            case 0x0202:
                if (@{{y}}['__v'] == 0) throw @{{ZeroDivisionError}}('integer division or modulo by zero');
                var f = Math['floor'](@{{x}}['__v'] / @{{y}}['__v']);
                return @{{tuple}}([new @{{int}}(f), new @{{int}}(@{{x}}['__v'] - f * @{{y}}['__v'])]);
            case 0x0204:
                return @{{y}}['__rdivmod__'](new @{{long}}(@{{x}}['__v']));
            case 0x0402:
                return @{{x}}['__divmod__'](new @{{long}}(@{{y}}['__v']));
            case 0x0404:
                return @{{x}}['__divmod__'](@{{y}});
        }
        if (!@{{x}}['__number__']) {
            if (   !@{{y}}['__number__']
                && @{{x}}['__mro__']['length'] > @{{y}}['__mro__']['length']
                && @{{isinstance}}(@{{x}}, @{{y}})
                && typeof @{{x}}['__divmod__'] == 'function')
                return @{{y}}['__divmod__'](@{{x}});
            if (typeof @{{x}}['__divmod__'] == 'function') return @{{x}}['__divmod__'](@{{y}});
        }
        if (!@{{y}}['__number__'] && typeof @{{y}}['__rdivmod__'] == 'function') return @{{y}}['__rdivmod__'](@{{x}});
    }
""")
    raise TypeError("unsupported operand type(s) for divmod(): '%r', '%r'" % (x, y))

def all(iterable):
    for element in iterable:
        if not element:
            return False
    return True

def any(iterable):
    for element in iterable:
        if element:
            return True
    return False

### begin from pypy 2.7.1 string formatter (newformat.py)
# Adaptation of the str format() method from pypy 2.7.1
# Copyright (C) 2011, Anthon van der Neut <a.van.der.neut@ruamel.eu>


class StringBuilder(object):
    def __init__(self):
        self.l = []
        self.tp = str

    def append(self, s):
        #assert isinstance(s, self.tp)
        self.l.append(s)

    def append_slice(self, s, start, end):
        ## these asserts give problems in pyjs
        #assert isinstance(s, str)
        #assert 0 <= start <= end <= len(s)
        self.l.append(s[start:end])

    def append_multiple_char(self, c, times):
        #assert isinstance(c, self.tp)
        self.l.append(c * times)

    def build(self):
        return self.tp("").join(self.l)

#@specialize.argtype(1)
def _parse_int(s, start, end):
    """Parse a number and check for overflows"""
    result = 0
    i = start
    while i < end:
        c = ord(s[i])
        if ord("0") <= c <= ord("9"):
            try:
                result = result * 10
                if result > 1000000000: # this is not going to overflow in CPython
                    raise OverflowError
            except OverflowError:
                msg = "too many decimal digits in format string"
                raise ValueError(msg)
            result += c - ord("0")
        else:
            break
        i += 1
    if i == start:
        result = -1
    return result, i

class TemplateFormatter(object):

    # Auto number state
    ANS_INIT = 1
    ANS_AUTO = 2
    ANS_MANUAL = 3

    def __init__(self, space, template):
        self.space = space
        self.empty = ""
        self.template = template
        self.parser_list_w = None # used to be a class variable

    def build(self, args, kw):
        self.args, self.kwargs = args, kw
        self.auto_numbering = 0
        self.auto_numbering_state = self.ANS_INIT
        return self._build_string(0, len(self.template), 2)

    def _build_string(self, start, end, level):
        out = StringBuilder()
        if not level:
            raise ValueError("Recursion depth exceeded")
        level -= 1
        s = self.template
        return self._do_build_string(start, end, level, out, s)

    def _do_build_string(self, start, end, level, out, s):
        last_literal = i = start
        while i < end:
            c = s[i]
            i += 1
            if c == "{" or c == "}":
                at_end = i == end
                # Find escaped "{" and "}"
                markup_follows = True
                if c == "}":
                    if at_end or s[i] != "}":
                        raise ValueError("Single '}'")
                    i += 1
                    markup_follows = False
                if c == "{":
                    if at_end:
                        raise ValueError("Single '{'")
                    if s[i] == "{":
                        i += 1
                        markup_follows = False
                # Attach literal data
                out.append_slice(s, last_literal, i - 1)
                if not markup_follows:
                    last_literal = i
                    continue
                nested = 1
                field_start = i
                recursive = False
                while i < end:
                    c = s[i]
                    if c == "{":
                        recursive = True
                        nested += 1
                    elif c == "}":
                        nested -= 1
                        if not nested:
                            break
                    i += 1
                if nested:
                    raise ValueError("Unmatched '{'")
                rendered = self._render_field(field_start, i, recursive, level)
                out.append(rendered)
                i += 1
                last_literal = i

        out.append_slice(s, last_literal, end)
        return out.build()

    # This is only ever called if we're already unrolling _do_build_string
    def _parse_field(self, start, end):
        s = self.template
        # Find ":" or "!"
        i = start
        while i < end:
            c = s[i]
            if c == ":" or c == "!":
                end_name = i
                if c == "!":
                    i += 1
                    if i == end:
                        w_msg = "expected conversion"
                        raise ValueError(w_msg)
                    conversion = s[i]
                    i += 1
                    if i < end:
                        if s[i] != ':':
                            w_msg = "expected ':' after format specifier"
                            raise ValueError(w_msg)
                        i += 1
                else:
                    conversion = None
                    i += 1
                return s[start:end_name], conversion, i
            i += 1
        return s[start:end], None, end

    def _get_argument(self, name):
        # First, find the argument.
        i = 0
        end = len(name)
        while i < end:
            c = name[i]
            if c == "[" or c == ".":
                break
            i += 1
        empty = not i
        if empty:
            index = -1
        else:
            index, stop = _parse_int(name, 0, i)
            if stop != i:
                index = -1
        use_numeric = empty or index != -1
        if self.auto_numbering_state == self.ANS_INIT and use_numeric:
            if empty:
                self.auto_numbering_state = self.ANS_AUTO
            else:
                self.auto_numbering_state = self.ANS_MANUAL
        if use_numeric:
            if self.auto_numbering_state == self.ANS_MANUAL:
                if empty:
                    msg = "switching from manual to automatic numbering"
                    raise ValueError(msg)
            elif not empty:
                msg = "switching from automatic to manual numbering"
                raise ValueError(msg)
        if empty:
            index = self.auto_numbering
            self.auto_numbering += 1
        if index == -1:
            kwarg = name[:i]
            arg_key = kwarg
            try:
                w_arg = self.kwargs[arg_key]
            except KeyError:
                raise KeyError(arg_key)
        else:
            try:
                w_arg = self.args[index]
            except IndexError:
                w_msg = "index out of range"
                raise IndexError(w_msg)
            except:
                raise
        return self._resolve_lookups(w_arg, name, i, end)

    def _resolve_lookups(self, w_obj, name, start, end):
        # Resolve attribute and item lookups.
        i = start
        while i < end:
            c = name[i]
            if c == ".":
                i += 1
                start = i
                while i < end:
                    c = name[i]
                    if c == "[" or c == ".":
                        break
                    i += 1
                if start == i:
                    w_msg = "Empty attribute in format string"
                    raise ValueError(w_msg)
                w_attr = name[start:i]
                if w_obj is not None:
                    w_obj = getattr(w_obj, w_attr)
                else:
                    self.parser_list_w.append(self.space.newtuple([
                        self.space.w_True, w_attr]))
            elif c == "[":
                got_bracket = False
                i += 1
                start = i
                while i < end:
                    c = name[i]
                    if c == "]":
                        got_bracket = True
                        break
                    i += 1
                if not got_bracket:
                    raise ValueError("Missing ']'")
                if name[start] == '{':
                    # CPython raise TypeError on '{0[{1}]}', pyjs converts
                    raise TypeError('no replacement on fieldname')
                index, reached = _parse_int(name, start, i)
                if index != -1 and reached == i:
                    w_item = index
                else:
                    w_item = name[start:i]
                i += 1 # Skip "]"
                if w_obj is not None:
                    w_obj = w_obj[w_item]
                else:
                    self.parser_list_w.append(self.space.newtuple([
                        self.space.w_False, w_item]))
            else:
                msg = "Only '[' and '.' may follow ']'"
                raise ValueError(msg)
        return w_obj

    def formatter_field_name_split(self):
        name = self.template
        i = 0
        end = len(name)
        while i < end:
            c = name[i]
            if c == "[" or c == ".":
                break
            i += 1
        if i == 0:
            index = -1
        else:
            index, stop = _parse_int(name, 0, i)
            if stop != i:
                index = -1
        if index >= 0:
            w_first = index
        else:
            w_first = name[:i]
        #
        self.parser_list_w = []
        self._resolve_lookups(None, name, i, end)
        #
        return self.space.newtuple([w_first,
                               self.space.iter(self.space.newlist(self.parser_list_w))])

    def _convert(self, w_obj, conversion):
        conv = conversion[0]
        if conv == "r":
            return repr(w_obj)
        elif conv == "s":
            return str(w_obj)
        else:
            raise ValueError("invalid conversion")

    def _render_field(self, start, end, recursive, level):
        name, conversion, spec_start = self._parse_field(start, end)
        spec = self.template[spec_start:end]
        # when used from formatter_parser()
        if self.parser_list_w is not None:
            if level == 1:    # ignore recursive calls
                startm1 = start - 1
                assert startm1 >= self.last_end
                w_entry = self.space.newtuple([
                    self.template[self.last_end:startm1],
                    name,
                    spec,
                    conversion])
                self.parser_list_w.append(w_entry)
                self.last_end = end + 1
            return self.empty
        #
        w_obj = self._get_argument(name)
        if conversion is not None:
            w_obj = self._convert(w_obj, conversion)
        if recursive:
            spec = self._build_string(spec_start, end, level)
        w_rendered = self.space.format(w_obj, spec)
        return str(w_rendered)

    def formatter_parser(self):
        self.parser_list_w = []
        self.last_end = 0
        self._build_string(0, len(self.template), 2)
        #
        if self.last_end < len(self.template):
            w_lastentry = self.space.newtuple([
                self.template[self.last_end:],
                self.space.w_None,
                self.space.w_None,
                self.space.w_None])
            self.parser_list_w.append(w_lastentry)
        return self.space.iter(self.space.newlist(self.parser_list_w))


class NumberSpec(object):
    pass

class BaseFormatter(object):

    def format_int_or_long(self, w_num, kind):
        raise NotImplementedError

    def format_float(self, w_num):
        raise NotImplementedError

    def format_complex(self, w_num):
        raise NotImplementedError


INT_KIND = 1
LONG_KIND = 2

NO_LOCALE = 1
DEFAULT_LOCALE = 2
CURRENT_LOCALE = 3


class Formatter(BaseFormatter):
    """__format__ implementation for builtin types."""

    _grouped_digits = None

    def __init__(self, space, spec):
        self.space = space
        self.empty = ""
        self.spec = spec

    def _is_alignment(self, c):
        return (c == "<" or
                c == ">" or
                c == "=" or
                c == "^")

    def _is_sign(self, c):
        return (c == " " or
                c == "+" or
                c == "-")

    def _parse_spec(self, default_type, default_align):
        self._fill_char = self._lit("\0")[0]
        self._align = default_align
        self._alternate = False
        self._sign = "\0"
        self._thousands_sep = False
        self._precision = -1
        the_type = default_type
        spec = self.spec
        if not spec:
            return True
        length = len(spec)
        i = 0
        got_align = True
        if length - i >= 2 and self._is_alignment(spec[i + 1]):
            self._align = spec[i + 1]
            self._fill_char = spec[i]
            i += 2
        elif length - i >= 1 and self._is_alignment(spec[i]):
            self._align = spec[i]
            i += 1
        else:
            got_align = False
        if length - i >= 1 and self._is_sign(spec[i]):
            self._sign = spec[i]
            i += 1
        if length - i >= 1 and spec[i] == "#":
            self._alternate = True
            i += 1
        if self._fill_char == "\0" and length - i >= 1 and spec[i] == "0":
            self._fill_char = self._lit("0")[0]
            if not got_align:
                self._align = "="
            i += 1
        start_i = i
        self._width, i = _parse_int(spec, i, length)
        if length != i and spec[i] == ",":
            self._thousands_sep = True
            i += 1
        if length != i and spec[i] == ".":
            i += 1
            self._precision, i = _parse_int(spec, i, length)
            if self._precision == -1:
                raise ValueError("no precision given")
        if length - i > 1:
            raise ValueError("invalid format spec")
        if length - i == 1:
            presentation_type = spec[i]
            the_type = presentation_type
            i += 1
        self._type = the_type
        if self._thousands_sep:
            tp = self._type
            if (tp == "d" or
                tp == "e" or
                tp == "f" or
                tp == "g" or
                tp == "E" or
                tp == "G" or
                tp == "%" or
                tp == "F" or
                tp == "\0"):
                # ok
                pass
            else:
                raise ValueError("invalid type with ','")
        return False

    def _calc_padding(self, string, length):
        """compute left and right padding, return total width of string"""
        if self._width != -1 and length < self._width:
            total = self._width
        else:
            total = length
        align = self._align
        if align == ">":
            left = total - length
        elif align == "^":
            left = (total - length) / 2
        elif align == "<" or align == "=":
            left = 0
        else:
            raise AssertionError("shouldn't be here")
        right = total - length - left
        self._left_pad = left
        self._right_pad = right
        return total

    def _lit(self, s):
        return s

    def _pad(self, string):
        builder = self._builder()
        builder.append_multiple_char(self._fill_char, self._left_pad)
        builder.append(string)
        builder.append_multiple_char(self._fill_char, self._right_pad)
        return builder.build()

    def _builder(self):
        return StringBuilder()

    def _unknown_presentation(self, tp):
        msg = "unknown presentation for %s: '%s'"
        w_msg = msg  % (tp, self._type)
        raise ValueError(w_msg)

    def format_string(self, string):
        if self._parse_spec("s", "<"):
            return string
        if self._type != "s":
            self._unknown_presentation("string")
        if self._sign != "\0":
            msg = "Sign not allowed in string format specifier"
            raise ValueError(msg)
        if self._alternate:
            msg = "Alternate form not allowed in string format specifier"
            raise ValueError(msg)
        if self._align == "=":
            msg = "'=' alignment not allowed in string format specifier"
            raise ValueError(msg)
        length = len(string)
        precision = self._precision
        if precision != -1 and length >= precision:
            assert precision >= 0
            length = precision
            string = string[:precision]
        if self._fill_char == "\0":
            self._fill_char = self._lit(" ")[0]
        self._calc_padding(string, length)
        return self._pad(string)

    def _get_locale(self, tp):
        if tp == "n":
            dec, thousands, grouping = numeric_formatting()
        elif self._thousands_sep:
            dec = "."
            thousands = ","
            grouping = "\3\0"
        else:
            dec = "."
            thousands = ""
            grouping = "\256"
        self._loc_dec = dec
        self._loc_thousands = thousands
        self._loc_grouping = grouping

    def _calc_num_width(self, n_prefix, sign_char, to_number, n_number,
                        n_remainder, has_dec, digits):
        """Calculate widths of all parts of formatted number.

        Output will look like:

            <lpadding> <sign> <prefix> <spadding> <grouped_digits> <decimal>
            <remainder> <rpadding>

        sign is computed from self._sign, and the sign of the number
        prefix is given
        digits is known
        """
        spec = NumberSpec()
        spec.n_digits = n_number - n_remainder - has_dec
        spec.n_prefix = n_prefix
        spec.n_lpadding = 0
        spec.n_decimal = int(has_dec)
        spec.n_remainder = n_remainder
        spec.n_spadding = 0
        spec.n_rpadding = 0
        spec.n_min_width = 0
        spec.n_total = 0
        spec.sign = "\0"
        spec.n_sign = 0
        sign = self._sign
        if sign == "+":
            spec.n_sign = 1
            spec.sign = "-" if sign_char == "-" else "+"
        elif sign == " ":
            spec.n_sign = 1
            spec.sign = "-" if sign_char == "-" else " "
        elif sign_char == "-":
            spec.n_sign = 1
            spec.sign = "-"
        extra_length = (spec.n_sign + spec.n_prefix + spec.n_decimal +
                        spec.n_remainder) # Not padding or digits
        if self._fill_char == "0" and self._align == "=":
            spec.n_min_width = self._width - extra_length
        if self._loc_thousands:
            self._group_digits(spec, digits[to_number:])
            n_grouped_digits = len(self._grouped_digits)
        else:
            n_grouped_digits = spec.n_digits
        n_padding = self._width - (extra_length + n_grouped_digits)
        if n_padding > 0:
            align = self._align
            if align == "<":
                spec.n_rpadding = n_padding
            elif align == ">":
                spec.n_lpadding = n_padding
            elif align == "^":
                spec.n_lpadding = n_padding // 2
                spec.n_rpadding = n_padding - spec.n_lpadding
            elif align == "=":
                spec.n_spadding = n_padding
            else:
                raise AssertionError("shouldn't reach")
        spec.n_total = spec.n_lpadding + spec.n_sign + spec.n_prefix + \
                       spec.n_spadding + n_grouped_digits + \
                       spec.n_decimal + spec.n_remainder + spec.n_rpadding
        return spec

    def _fill_digits(self, buf, digits, d_state, n_chars, n_zeros,
                     thousands_sep):
        if thousands_sep:
            for c in thousands_sep:
                buf.append(c)
        for i in range(d_state - 1, d_state - n_chars - 1, -1):
            buf.append(digits[i])
        for i in range(n_zeros):
            buf.append("0")

    def _group_digits(self, spec, digits):
        buf = []
        grouping = self._loc_grouping
        min_width = spec.n_min_width
        grouping_state = 0
        count = 0
        left = spec.n_digits
        n_ts = len(self._loc_thousands)
        need_separator = False
        done = False
        groupings = len(grouping)
        previous = 0
        while True:
            group = ord(grouping[grouping_state])
            if group > 0:
                if group == 256:
                    break
                grouping_state += 1
                previous = group
            else:
                group = previous
            final_grouping = min(group, max(left, max(min_width, 1)))
            n_zeros = max(0, final_grouping - left)
            n_chars = max(0, min(left, final_grouping))
            ts = self._loc_thousands if need_separator else None
            self._fill_digits(buf, digits, left, n_chars, n_zeros, ts)
            need_separator = True
            left -= n_chars
            min_width -= final_grouping
            if left <= 0 and min_width <= 0:
                done = True
                break
            min_width -= n_ts
        if not done:
            group = max(max(left, min_width), 1)
            n_zeros = max(0, group - left)
            n_chars = max(0, min(left, group))
            ts = self._loc_thousands if need_separator else None
            self._fill_digits(buf, digits, left, n_chars, n_zeros, ts)
        buf.reverse()
        self._grouped_digits = self.empty.join(buf)

    def _upcase_string(self, s):
        buf = []
        for c in s:
            index = ord(c)
            if ord("a") <= index <= ord("z"):
                c = chr(index - 32)
            buf.append(c)
        return self.empty.join(buf)


    def _fill_number(self, spec, num, to_digits, to_prefix, fill_char,
                     to_remainder, upper, grouped_digits=None):
        out = self._builder()
        if spec.n_lpadding:
            out.append_multiple_char(fill_char[0], spec.n_lpadding)
        if spec.n_sign:
            sign = spec.sign
            out.append(sign)
        if spec.n_prefix:
            pref = num[to_prefix:to_prefix + spec.n_prefix]
            if upper:
                pref = self._upcase_string(pref)
            out.append(pref)
        if spec.n_spadding:
            out.append_multiple_char(fill_char[0], spec.n_spadding)
        if spec.n_digits != 0:
            if self._loc_thousands:
                if grouped_digits is not None:
                    digits = grouped_digits
                else:
                    digits = self._grouped_digits
                    assert digits is not None
            else:
                stop = to_digits + spec.n_digits
                assert stop >= 0
                digits = num[to_digits:stop]
            if upper:
                digits = self._upcase_string(digits)
            out.append(digits)
        if spec.n_decimal:
            out.append(".")
        if spec.n_remainder:
            out.append(num[to_remainder:])
        if spec.n_rpadding:
            out.append_multiple_char(fill_char[0], spec.n_rpadding)
        #if complex, need to call twice - just retun the buffer
        return out.build()

    def _format_int_or_long(self, w_num, kind):
        if self._precision != -1:
            msg = "precision not allowed in integer type"
            raise ValueError(msg)
        sign_char = "\0"
        tp = self._type
        if tp == "c":
            if self._sign != "\0":
                msg = "sign not allowed with 'c' presentation type"
                raise ValueError(msg)
            value = w_num
            result = chr(value)
            n_digits = 1
            n_remainder = 1
            to_remainder = 0
            n_prefix = 0
            to_prefix = 0
            to_numeric = 0
        else:
            if tp == "b":
                base = 2
                skip_leading = 2
            elif tp == "o":
                base = 8
                skip_leading = 2
            elif tp == "x" or tp == "X":
                base = 16
                skip_leading = 2
            elif tp == "n" or tp == "d":
                base = 10
                skip_leading = 0
            else:
                raise AssertionError("shouldn't reach")
            if kind == INT_KIND:
                result = self._int_to_base(base, w_num)
            else:
                result = self._int_to_base(base, w_num)
            n_prefix = skip_leading if self._alternate else 0
            to_prefix = 0
            if result[0] == "-":
                sign_char = "-"
                skip_leading += 1
                to_prefix += 1
            n_digits = len(result) - skip_leading
            n_remainder = 0
            to_remainder = 0
            to_numeric = skip_leading
        self._get_locale(tp)
        spec = self._calc_num_width(n_prefix, sign_char, to_numeric, n_digits,
                                    n_remainder, False, result)
        fill = self._lit(" ") if self._fill_char == "\0" else self._fill_char
        upper = self._type == "X"
        return self._fill_number(spec, result, to_numeric,
                                 to_prefix, fill, to_remainder, upper)

    def _int_to_base(self, base, value):
        if base == 10:
            return str(value)
        # This part is slow.
        negative = value < 0
        value = abs(value)
        buf = ["\0"] * (8 * 8 + 6) # Too much on 32 bit, but who cares?
        i = len(buf) - 1
        while True:
            div = value // base
            mod = value - div * base
            digit = abs(mod)
            digit += ord("0") if digit < 10 else ord("a") - 10
            buf[i] = chr(digit)
            value = div
            i -= 1
            if not value:
                break
        if base == 2:
            buf[i] = "b"
            buf[i - 1] = "0"
        elif base == 8:
            buf[i] = "o"
            buf[i - 1] = "0"
        elif base == 16:
            buf[i] = "x"
            buf[i - 1] = "0"
        else:
            buf[i] = "#"
            buf[i - 1] = chr(ord("0") + base % 10)
            if base > 10:
                buf[i - 2] = chr(ord("0") + base // 10)
                i -= 1
        i -= 1
        if negative:
            i -= 1
            buf[i] = "-"
        assert i >= 0
        return self.empty.join(buf[i:])

    def format_int_or_long(self, w_num, kind):
        if self._parse_spec("d", ">"):
            return self.space.str(w_num)
        tp = self._type
        if (tp == "b" or
            tp == "c" or
            tp == "d" or
            tp == "o" or
            tp == "x" or
            tp == "X" or
            tp == "n"):
            return self._format_int_or_long(w_num, kind)
        elif (tp == "e" or
              tp == "E" or
              tp == "f" or
              tp == "F" or
              tp == "g" or
              tp == "G" or
              tp == "%"):
            w_float = float(w_num)
            return self._format_float(w_float)
        else:
            self._unknown_presentation("int" if kind == INT_KIND else "long")

    def _parse_number(self, s, i):
        """Determine if s has a decimal point, and the index of the first #
        after the decimal, or the end of the number."""
        length = len(s)
        while i < length and "0" <= s[i] <= "9":
            i += 1
        rest = i
        dec_point = i < length and s[i] == "."
        if dec_point:
            rest += 1
        #differs from CPython method - CPython sets n_remainder
        return dec_point, rest

    def _format_float(self, w_float):
        """helper for format_float"""
        flags = 0
        default_precision = 6
        if self._alternate:
            msg = "alternate form not allowed in float formats"
            raise ValueError(msg)
        tp = self._type
        self._get_locale(tp)
        if tp == "\0":
            tp = "g"
            default_precision = 12
            flags |= DTSF_ADD_DOT_0
        elif tp == "n":
            tp = "g"
        value = float(w_float)
        if tp == "%":
            tp = "f"
            value *= 100
            add_pct = True
        else:
            add_pct = False
        if self._precision == -1:
            self._precision = default_precision
        result = formatd(value, tp, self._precision, flags)
        if add_pct:
            result += "%"
        n_digits = len(result)
        if result[0] == "-":
            sign = "-"
            to_number = 1
            n_digits -= 1
        else:
            sign = "\0"
            to_number = 0
        have_dec_point, to_remainder = self._parse_number(result, to_number)
        n_remainder = len(result) - to_remainder
        digits = result
        spec = self._calc_num_width(0, sign, to_number, n_digits,
                                    n_remainder, have_dec_point, digits)
        fill = self._lit(" ") if self._fill_char == "\0" else self._fill_char
        return self._fill_number(spec, digits, to_number, 0,
                                  fill, to_remainder, False)

    def format_float(self, w_float):
        if self._parse_spec("\0", ">"):
            return self.space.str(w_float)
        tp = self._type
        if (tp == "\0" or
            tp == "e" or
            tp == "E" or
            tp == "f" or
            tp == "F" or
            tp == "g" or
            tp == "G" or
            tp == "n" or
            tp == "%"):
            return self._format_float(w_float)
        self._unknown_presentation("float")

    def _format_complex(self, w_complex):
        tp = self._type
        self._get_locale(tp)
        default_precision = 6
        if self._align == "=":
            # '=' alignment is invalid
            msg = ("'=' alignment flag is not allowed in"
                   " complex format specifier")
            raise ValueError(msg)
        if self._fill_char == "0":
            #zero padding is invalid
            msg = "Zero padding is not allowed in complex format specifier"
            raise ValueError(msg)
        if self._alternate:
            #alternate is invalid
            msg = "Alternate form %s not allowed in complex format specifier"
            raise ValueError(msg % (self._alternate))
        skip_re = 0
        add_parens = 0
        if tp == "\0":
            #should mirror str() output
            tp = "g"
            default_precision = 12
            #test if real part is non-zero
            if (w_complex.realval == 0 and
                copysign(1., w_complex.realval) == 1.):
                skip_re = 1
            else:
                add_parens = 1

        if tp == "n":
            #same as 'g' except for locale, taken care of later
            tp = "g"

        #check if precision not set
        if self._precision == -1:
            self._precision = default_precision

        #might want to switch to double_to_string from formatd
        #in CPython it's named 're' - clashes with re module
        re_num = formatd(w_complex.realval, tp, self._precision)
        im_num = formatd(w_complex.imagval, tp, self._precision)
        n_re_digits = len(re_num)
        n_im_digits = len(im_num)

        to_real_number = 0
        to_imag_number = 0
        re_sign = im_sign = ''
        #if a sign character is in the output, remember it and skip
        if re_num[0] == "-":
            re_sign = "-"
            to_real_number = 1
            n_re_digits -= 1
        if im_num[0] == "-":
            im_sign = "-"
            to_imag_number = 1
            n_im_digits -= 1

        #turn off padding - do it after number composition
        #calc_num_width uses self._width, so assign to temporary variable,
        #calculate width of real and imag parts, then reassign padding, align
        tmp_fill_char = self._fill_char
        tmp_align = self._align
        tmp_width = self._width
        self._fill_char = "\0"
        self._align = "<"
        self._width = -1

        #determine if we have remainder, might include dec or exponent or both
        re_have_dec, re_remainder_ptr = self._parse_number(re_num,
                                                           to_real_number)
        im_have_dec, im_remainder_ptr = self._parse_number(im_num,
                                                           to_imag_number)

        #set remainder, in CPython _parse_number sets this
        #using n_re_digits causes tests to fail
        re_n_remainder = len(re_num) - re_remainder_ptr
        im_n_remainder = len(im_num) - im_remainder_ptr
        re_spec = self._calc_num_width(0, re_sign, to_real_number, n_re_digits,
                                       re_n_remainder, re_have_dec,
                                       re_num)

        #capture grouped digits b/c _fill_number reads from self._grouped_digits
        #self._grouped_digits will get overwritten in imaginary calc_num_width
        re_grouped_digits = self._grouped_digits
        if not skip_re:
            self._sign = "+"
        im_spec = self._calc_num_width(0, im_sign, to_imag_number, n_im_digits,
                                       im_n_remainder, im_have_dec,
                                       im_num)

        im_grouped_digits = self._grouped_digits
        if skip_re:
            re_spec.n_total = 0

        #reassign width, alignment, fill character
        self._align = tmp_align
        self._width = tmp_width
        self._fill_char = tmp_fill_char

        #compute L and R padding - stored in self._left_pad and self._right_pad
        self._calc_padding(self.empty, re_spec.n_total + im_spec.n_total + 1 +
                                       add_parens * 2)

        out = self._builder()
        fill = self._fill_char
        if fill == "\0":
            fill = self._lit(" ")[0]

        #compose the string
        #add left padding
        out.append_multiple_char(fill, self._left_pad)
        if add_parens:
            out.append(self._lit('(')[0])

        #if the no. has a real component, add it
        if not skip_re:
            out.append(self._fill_number(re_spec, re_num, to_real_number, 0,
                                         fill, re_remainder_ptr, False,
                                         re_grouped_digits))

        #add imaginary component
        out.append(self._fill_number(im_spec, im_num, to_imag_number, 0,
                                     fill, im_remainder_ptr, False,
                                     im_grouped_digits))

        #add 'j' character
        out.append(self._lit('j')[0])

        if add_parens:
            out.append(self._lit(')')[0])

        #add right padding
        out.append_multiple_char(fill, self._right_pad)

        return out.build()


    def format_complex(self, w_complex):
        """return the string representation of a complex number"""
        #parse format specification, set associated variables
        if self._parse_spec("\0", ">"):
            return self.space.str(w_complex)
        tp = self._type
        if (tp == "\0" or
            tp == "e" or
            tp == "E" or
            tp == "f" or
            tp == "F" or
            tp == "g" or
            tp == "G" or
            tp == "n"):
            return self._format_complex(w_complex)
        self._unknown_presentation("complex")

class StringFormatSpace(object):
    def format(self, w_obj, spec):
        # added test on int, float, basestring CPython has __format__ for them
        if isinstance(w_obj, object) and \
           not isinstance(w_obj, (int, float, basestring)):
            if hasattr(w_obj, '__format__'):
                return w_obj.__format__(spec)
        if not spec:
            return w_obj
        fmt = Formatter(self, spec)
        if isinstance(w_obj, basestring):
            return fmt.format_string(w_obj)
        elif isinstance(w_obj, int):
            return fmt.format_int_or_long(w_obj, spec)
        elif isinstance(w_obj, float):
            return fmt.format_float(w_obj)
        if isinstance(w_obj, object):
            if hasattr(w_obj, '__str__'):
                return fmt.format_string(w_obj.__str__())
        print 'type not implemented'
        return w_obj


DTSF_STR_PRECISION = 12

DTSF_SIGN      = 0x1
DTSF_ADD_DOT_0 = 0x2
DTSF_ALT       = 0x4

DIST_FINITE   = 1
DIST_NAN      = 2
DIST_INFINITY = 3

# Equivalent to CPython's PyOS_double_to_string
def formatd(x, code, precision, flags=0):
    if flags & DTSF_ALT:
        alt = '#'
    else:
        alt = ''

    if code == 'r':
        fmt = "%r"
    else:
        fmt = "%%%s.%d%s" % (alt, precision, code)
    s = fmt % (x,)

    if flags & DTSF_ADD_DOT_0:
        # We want float numbers to be recognizable as such,
        # i.e., they should contain a decimal point or an exponent.
        # However, %g may print the number as an integer;
        # in such cases, we append ".0" to the string.
        idx = len(s)
        for idx in range(len(s),0, -1):
            c = s[idx-1]
            # this is to solve Issue #672
            if c in 'eE':
                if s[idx] in '+-':
                    idx += 1
                s = s[:idx] + '%02d' % (int(s[idx:]))
                break
            if c in '.eE':
                break
        else:
            if len(s) < precision:
                s += '.0'
            else: # for numbers truncated by javascripts toPrecision()
                sign = '+'
                if x < 1:
                    sign = '-'
                s = '%s.%se%s%02d' % (s[0], s[1:], sign, len(s) - 1)
    elif code == 'r' and s.endswith('.0'):
        s = s[:-2]

    return s

def numeric_formatting():
    # return decimal, thousands and grouping
    return '.', ',', "\3\0"

def _string_format(s, args=[], kw={}):
    space = StringFormatSpace()
    fm = TemplateFormatter(space, s)
    res = fm.build(args, kw)
    return res

def format(val, spec=''):
    args = [val]
    space = StringFormatSpace()
    return str(space.format(val, spec))


### end from pypy 2.7.1 string formatter (newformat.py)

__iter_prepare = JS("""function(iter, reuse_tuple) {

    if (typeof iter == 'undefined') {
        throw @{{TypeError}}("iter is undefined");
    }
    var it = {};
    it['$iter'] = iter;
    it['$loopvar'] = 0;
    it['$reuse_tuple'] = reuse_tuple;
    if (typeof (it['$arr'] = iter['__array']) != 'undefined') {
        it['$gentype'] = 0;
    } else {
        it['$iter'] = iter['__iter__']();
        it['$gentype'] = typeof (it['$arr'] = iter['__array']) != 'undefined'? 0 : (typeof iter['$genfunc'] == 'function'? 1 : -1);
    }
    return it;
}""")

__wrapped_next = JS("""function(it) {
    var iterator = it['$iter'];
    it['$nextval'] = it['$gentype']?(it['$gentype'] > 0?
        iterator['next'](true,it['$reuse_tuple']):@{{wrapped_next}}(iterator)
                              ) : it['$arr'][it['$loopvar']++];
    return it;
}""")

# For optimized for loops: fall back for userdef iterators
wrapped_next = JS("""function (iter) {
    try {
        var res = iter['next']();
    } catch (e) {
        if (@{{isinstance}}(e, @{{StopIteration}})) {
            return;
        }
        throw e;
    }
    return res;
}""")

# Slice `data` in `count`-long array.
# If not `extended`, make sure `data` length is same as count
# Otherwise put all excessive elements in new array at `extended` position
__ass_unpack = JS("""function (data, count, extended) {
    if (data === null) {
        throw @{{TypeError}}("'NoneType' is not iterable");
    }
    if (data['constructor'] === Array) {
    } else if (typeof data['__iter__'] == 'function') {
        if (typeof data['__array'] == 'object') {
            data = data['__array'];
        } else {
            var iter = data['__iter__']();
            if (typeof iter['__array'] == 'object') {
                data = iter['__array'];
            }
            data = [];
            var item, i = 0;
            if (typeof iter['$genfunc'] == 'function') {
                while (typeof (item=iter['next'](true)) != 'undefined') {
                    data[i++] = item;
                }
            } else {
                try {
                    while (true) {
                        data[i++] = iter['next']();
                    }
                }
                catch (e) {
                    if (e['__name__'] != 'StopIteration') throw e;
                }
            }
        }
    } else {
        throw @{{TypeError}}("'" + @{{repr}}(data) + "' is not iterable");
    }
    var res = new Array();
    if (typeof extended == 'undefined' || extended === null)
    {
        if (data['length'] != count)
        if (data['length'] > count)
            throw @{{ValueError}}("too many values to unpack");
        else
            throw @{{ValueError}}("need more than "+data['length']+" values to unpack");
        return data;
    }
    else
    {
        throw @{{NotImplemented}}("Extended unpacking is not implemented");
    }
}""")

def __with(mgr, func):
    """
    Copied verbatim from http://www.python.org/dev/peps/pep-0343/
    """
    exit = type(mgr).__exit__  # Not calling it yet
    value = type(mgr).__enter__(mgr)
    exc = True
    try:
        try:
            func(value)
        except:
            # The exceptional case is handled here
            exc = False
            if not exit(mgr, *sys.exc_info()):
                raise
            # The exception is swallowed if exit() returns true
    finally:
        # The normal and non-local-goto cases are handled here
        if exc:
            exit(mgr, None, None, None)

init()

Ellipsis = EllipsisType()

__nondynamic_modules__ = {}

def __import__(name, globals={}, locals={}, fromlist=[], level=-1):
    module = ___import___(name, None)
    if not module is None and hasattr(module, '__was_initialized__'):
        return module
    raise ImportError("No module named " + name)

import sys # needed for debug option
import dynamic # needed for ___import___


