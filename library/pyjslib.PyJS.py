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


# FIXME: dynamic=1, async=False, init=True are useless here (?)
def import_module(path, parent_module, module_name, dynamic=1, async=False, init=True):
    module = None
    JS("""
    @{{module}} = $pyjs['modules_hash'][@{{module_name}}];
    if (typeof @{{module}} == 'function' && @{{module}}['__was_initialized__'] == true) {
        return null;
    }
    if (@{{module_name}} == 'sys' || @{{module_name}} == 'pyjslib') {
        @{{module}}();
        return null;
    }
    """)
    names = module_name.split(".")
    importName = ''
    # Import all modules in the chain (import a.b.c)
    for name in names:
        importName += name
        JS("""@{{module}} = $pyjs['modules_hash'][@{{importName}}];""")
        if isUndefined(module):
            raise ImportError("No module named " + importName)
        if JS("@{{module}}['__was_initialized__'] != true"):
            # Module wasn't initialized
            module()
        importName += '.'
    return None

# FIXME: dynamic=1, async=False are useless here (?). Only dynamic modules
# are loaded with load_module and it's always "async"
@noSourceTracking
def load_module(path, parent_module, module_name, dynamic=1, async=False):
    """
    """

    JS("""
        var cache_file;
        var module = $pyjs['modules_hash'][@{{module_name}}];
        if (typeof module == 'function') {
            return true;
        }

        if (!@{{dynamic}}) {
            // There's no way we can load a none dynamic module
            return false;
        }

        if (@{{path}} == null)
        {
            @{{path}} = './';
        }

        var override_name = @{{sys}}['platform'] + "." + @{{module_name}};
        if (((@{{sys}}['overrides'] != null) &&
             (@{{sys}}['overrides']['has_key'](override_name))))
        {
            cache_file =  @{{sys}}['overrides']['__getitem__'](override_name) ;
        }
        else
        {
            cache_file =  @{{module_name}} ;
        }

        cache_file = (@{{path}} + cache_file + '['cache']['js']' ) ;

        //alert("cache " + cache_file + " " + module_name + " " + parent_module);

        var onload_fn = '';

        // this one tacks the script onto the end of the DOM
        pyjs_load_script(cache_file, onload_fn, @{{async}});

        try {
            var loaded = (typeof $pyjs['modules_hash'][@{{module_name}}] == 'function')
        } catch ( e ) {
        }
        if (loaded) {
            return true;
        }
        return false;
    """)

@noSourceTracking
def load_module_wait(proceed_fn, parent_mod, module_list, dynamic):
    module_list = module_list.getArray()
    JS("""

    var wait_count = 0;
    //var data = '';
    //var element = $doc['createElement']("div");
    //element['innerHTML'] = '';
    //$doc['body']['appendChild'](element);
    //function write_dom(txt) {
    //    element['innerHTML'] += txt;
    //}

    var timeoutperiod = 1;
    if (@{{dynamic}})
        var timeoutperiod = 1;

    var wait = function() {
        wait_count++;
        //write_dom(".");
        var loaded = true;
        for (var i in @{{module_list}}) {
            if (typeof $pyjs['modules_hash'][@{{module_list}}[i]] != 'function') {
                loaded = false;
                break;
            }
        }
        if (!loaded) {
            setTimeout(wait, timeoutperiod);
        } else {
            if (@{{proceed_fn}}['importDone'])
                @{{proceed_fn}}['importDone'](@{{proceed_fn}});
            else
                @{{proceed_fn}}();
            //$doc['body']['removeChild'](element);
        }
    }
    //write_dom("Loading modules ");
    wait();
""")

class Modload:

    # All to-be-imported module names are in app_modlist
    # Since we're only _loading_ the modules here, we can do that in almost
    # any order. There's one limitation: a child/sub module cannot be loaded
    # unless its parent is loaded. It has to be chained in the module list.
    # (1) $pyjs.modules.pyjamas
    # (2) $pyjs.modules.pyjamas.ui
    # (3) $pyjs.modules.pyjamas.ui.Widget
    # Therefore, all modules are collected and sorted on the depth (i.e. the
    # number of dots in it)
    # As long as we don't move on to the next depth unless all modules of the
    # previous depth are loaded, we won't trun into unchainable modules
    # The execution of the module code is done when the import statement is
    # reached, or after loading the modules for the main module.
    @noSourceTracking
    def __init__(self, path, app_modlist, app_imported_fn, dynamic,
                 parent_mod):
        self.app_modlist = app_modlist
        self.app_imported_fn = app_imported_fn
        self.path = path
        self.dynamic = dynamic
        self.parent_mod = parent_mod
        self.modules = {}
        for modlist in self.app_modlist:
            for mod in modlist:
                depth = len(mod.split('.'))
                if not self.modules.has_key(depth):
                    self.modules[depth] = []
                self.modules[depth].append(mod)
        self.depths = self.modules.keys()
        self.depths.sort()
        self.depths.reverse()

    @noSourceTracking
    def next(self):
        if not self.dynamic:
            # All modules are static. Just start the main module.
            self.app_imported_fn()
            return
        depth = self.depths.pop()
        # Initiate the loading of the modules.
        for app in self.modules[depth]:
            load_module(self.path, self.parent_mod, app, self.dynamic, True);

        if len(self.depths) == 0:
            # This is the last depth. Start the main module after loading these
            # modules.
            load_module_wait(self.app_imported_fn, self.parent_mod, self.modules[depth], self.dynamic)
        else:
            # After loading the modules, to the next depth.
            load_module_wait(getattr(self, "next"), self.parent_mod, self.modules[depth], self.dynamic)


def get_module(module_name):
    ev = "__mod = %s;" % module_name
    JS("pyjs_eval(@{{ev}});")
    return __mod

def preload_app_modules(path, app_modnames, app_imported_fn, dynamic,
                        parent_mod=None):

    loader = Modload(path, app_modnames, app_imported_fn, dynamic, parent_mod)
    loader.next()

class BaseException:

    message = ''

    def __init__(self, *args):
        self.args = args
        if len(args) == 1:
            self.message = args[0]

    def __getitem__(self, index):
        return self.args.__getitem__(index)

    def __str__(self):
        if len(self.args) is 0:
            return ''
        elif len(self.args) is 1:
            return str(self.message)
        return repr(self.args)

    def __repr__(self):
        return self.__name__ + repr(self.args)

    def toString(self):
        return str(self)

class Exception(BaseException):
    pass

class StandardError(Exception):
    pass

class TypeError(StandardError):
    pass

class AttributeError(StandardError):

    def toString(self):
        return "AttributeError: %s of %s" % (self.args[1], self.args[0])

class NameError(StandardError):
    pass

class ValueError(StandardError):
    pass

class ImportError(StandardError):
    pass

class LookupError(StandardError):

    def toString(self):
        return self.__name__ + ": " + self.args[0]

class KeyError(LookupError):

    def __str__(self):
        if len(self.args) is 0:
            return ''
        elif len(self.args) is 1:
            return repr(self.message)
        return repr(self.args)

class IndexError(LookupError):
    pass

# There seems to be an bug in Chrome with accessing the message
# property, on which an error is thrown
# Hence the declaration of 'var message' and the wrapping in try..catch
def init():
    JS("""
pyjslib['_errorMapping'] = function(err) {
    if (err instanceof(ReferenceError) || err instanceof(TypeError)) {
        var message = ''
        try {
            message = err['message'];
        } catch ( e) {
        }
        return pyjslib['AttributeError'](message);
    }
    return err
}

pyjslib['TryElse'] = function () { };
pyjslib['TryElse']['prototype'] = new Error();
pyjslib['TryElse']['__name__'] = 'TryElse';
pyjslib['TryElse']['message'] = 'TryElse';

pyjslib['StopIteration'] = function () { };
pyjslib['StopIteration']['prototype'] = new Error();
pyjslib['StopIteration']['__name__'] = 'StopIteration';
pyjslib['StopIteration']['message'] = 'StopIteration';

pyjslib['String_find'] = function(sub, start, end) {
    var pos=this['indexOf'](sub, start);
    if (pyjslib['isUndefined'](end)) return pos;

    if (pos + sub['length']>end) return -1;
    return pos;
}

pyjslib['String_join'] = function(data) {
    var text="";

    if (pyjslib['isArray'](data)) {
        return data['join'](this);
    }
    else if (pyjslib['isIteratable'](data)) {
        var iter=data['__iter__']();
        try {
            text+=iter['next']();
            while (true) {
                var item=iter['next']();
                text+=this + item;
            }
        }
        catch (e) {
            if (e['__name__'] != 'StopIteration') throw e;
        }
    }

    return text;
}

pyjslib['String_isdigit'] = function() {
    return (this['match'](/^\d+$/g) != null);
}

pyjslib['String_replace'] = function(old, replace, count) {
    var do_max=false;
    var start=0;
    var new_str="";
    var pos=0;

    if (!pyjslib['isString'](old)) return this['__replace'](old, replace);
    if (!pyjslib['isUndefined'](count)) do_max=true;

    while (start<this['length']) {
        if (do_max && !count--) break;

        pos=this['indexOf'](old, start);
        if (pos<0) break;

        new_str+=this['substring'](start, pos) + replace;
        start=pos+old['length'];
    }
    if (start<this['length']) new_str+=this['substring'](start);

    return new_str;
}

pyjslib['String_split'] = function(sep, maxsplit) {
    var items=new pyjslib['List']();
    var do_max=false;
    var subject=this;
    var start=0;
    var pos=0;

    if (pyjslib['isUndefined'](sep) || pyjslib['isNull'](sep)) {
        sep=" ";
        subject=subject['strip']();
        subject=subject['replace'](/\s+/g, sep);
    }
    else if (!pyjslib['isUndefined'](maxsplit)) do_max=true;

    if (subject['length'] == 0) {
        return items;
    }

    while (start<subject['length']) {
        if (do_max && !maxsplit--) break;

        pos=subject['indexOf'](sep, start);
        if (pos<0) break;

        items['append'](subject['substring'](start, pos));
        start=pos+sep['length'];
    }
    if (start<=subject['length']) items['append'](subject['substring'](start));

    return items;
}

pyjslib['String___iter__'] = function() {
    var i = 0;
    var s = this;
    return {
        'next': function() {
            if (i >= s['length']) {
                throw pyjslib['StopIteration'];
            }
            return s['substring'](i++, i, 1);
        },
        '__iter__': function() {
            return this;
        }
    };
}

pyjslib['String_strip'] = function(chars) {
    return this['lstrip'](chars)['rstrip'](chars);
}

pyjslib['String_lstrip'] = function(chars) {
    if (pyjslib['isUndefined'](chars)) return this['replace'](/^\s+/, "");

    return this['replace'](new RegExp("^[" + chars + "]+"), "");
}

pyjslib['String_rstrip'] = function(chars) {
    if (pyjslib['isUndefined'](chars)) return this['replace'](/\s+$/, "");

    return this['replace'](new RegExp("[" + chars + "]+$"), "");
}

pyjslib['String_startswith'] = function(prefix, start, end) {
    // FIXME: accept tuples as suffix (since 2['5'])
    if (pyjslib['isUndefined'](start)) start = 0;
    if (pyjslib['isUndefined'](end)) end = this['length'];

    if ((end - start) < prefix['length']) return false
    if (this['substr'](start, prefix['length']) == prefix) return true;
    return false;
}

pyjslib['String_endswith'] = function(suffix, start, end) {
    // FIXME: accept tuples as suffix (since 2['5'])
    if (pyjslib['isUndefined'](start)) start = 0;
    if (pyjslib['isUndefined'](end)) end = this['length'];

    if ((end - start) < suffix['length']) return false
    if (this['substr'](end - suffix['length'], suffix['length']) == suffix) return true;
    return false;
}

pyjslib['String_ljust'] = function(width, fillchar) {
    if (typeof(width) != 'number' ||
        parseInt(width) != width) {
        throw (pyjslib['TypeError']("an integer is required"));
    }
    if (pyjslib['isUndefined'](fillchar)) fillchar = ' ';
    if (typeof(fillchar) != 'string' ||
        fillchar['length'] != 1) {
        throw (pyjslib['TypeError']("ljust() argument 2 must be char, not " + typeof(fillchar)));
    }
    if (this['length'] >= width) return this;
    return this + new Array(width+1 - this['length'])['join'](fillchar);
}

pyjslib['String_rjust'] = function(width, fillchar) {
    if (typeof(width) != 'number' ||
        parseInt(width) != width) {
        throw (pyjslib['TypeError']("an integer is required"));
    }
    if (pyjslib['isUndefined'](fillchar)) fillchar = ' ';
    if (typeof(fillchar) != 'string' ||
        fillchar['length'] != 1) {
        throw (pyjslib['TypeError']("rjust() argument 2 must be char, not " + typeof(fillchar)));
    }
    if (this['length'] >= width) return this;
    return new Array(width + 1 - this['length'])['join'](fillchar) + this;
}

pyjslib['String_center'] = function(width, fillchar) {
    if (typeof(width) != 'number' ||
        parseInt(width) != width) {
        throw (pyjslib['TypeError']("an integer is required"));
    }
    if (pyjslib['isUndefined'](fillchar)) fillchar = ' ';
    if (typeof(fillchar) != 'string' ||
        fillchar['length'] != 1) {
        throw (pyjslib['TypeError']("center() argument 2 must be char, not " + typeof(fillchar)));
    }
    if (this['length'] >= width) return this;
    var padlen = width - this['length'];
    var right = Math['ceil'](padlen / 2);
    var left = padlen - right;
    return new Array(left+1)['join'](fillchar) + this + new Array(right+1)['join'](fillchar);
}

pyjslib['abs'] = Math['abs'];
""")

class Class:
    def __init__(self, name):
        self.name = name

    def __str___(self):
        return self.name

@noSourceTracking
def eq(a,b):
    # All 'python' classes and types are implemented as objects/functions.
    # So, for speed, do a typeof X / X.__cmp__  on a/b.
    # Checking for the existance of .__cmp__ is expensive...
    JS("""
    if (@{{a}} === null) {
        if (@{{b}} === null) return true;
        return false;
    }
    if (@{{b}} === null) {
        return false;
    }
    if ((typeof @{{a}} == 'object' || typeof @{{a}} == 'function') && typeof @{{a}}['__cmp__'] == 'function') {
        return @{{a}}['__cmp__'](@{{b}}) == 0;
    } else if ((typeof @{{b}} == 'object' || typeof @{{b}} == 'function') && typeof @{{b}}['__cmp__'] == 'function') {
        return @{{b}}['__cmp__'](@{{a}}) == 0;
    }
    return @{{a}} == @{{b}};
    """)

@noSourceTracking
def cmp(a,b):
    JS("""
    if (@{{a}} === null) {
        if (@{{b}} === null) return 0;
        return -1;
    }
    if (@{{b}} === null) {
        return 1;
    }
    if ((typeof @{{a}} == 'object' || typeof @{{a}} == 'function') && typeof @{{a}}['__cmp__'] == 'function') {
        return @{{a}}['__cmp__'](@{{b}});
    } else if ((typeof @{{b}} == 'object' || typeof @{{b}} == 'function') && typeof @{{b}}['__cmp__'] == 'function') {
        return -@{{b}}['__cmp__'](@{{a}});
    }
    if (@{{a}} > @{{b}}) return 1;
    if (@{{b}} > @{{a}}) return -1;
    return 0;
    """)

# For list.sort()
__cmp = cmp

@noSourceTracking
def bool(v):
    # this needs to stay in native code without any dependencies here,
    # because this is used by if and while, we need to prevent
    # recursion
    JS("""
    if (!@{{v}}) return false;
    switch(typeof @{{v}}){
    case 'boolean':
        return @{{v}};
    case 'object':
        if (@{{v}}['__nonzero__']){
            return @{{v}}['__nonzero__']();
        }else if (@{{v}}['__len__']){
            return @{{v}}['__len__']()>0;
        }
        return true;
    }
    return Boolean(@{{v}});
    """)

class List:
    @noSourceTracking
    def __init__(self, data=None):
        JS("""
        this['l'] = [];
        this['extend'](@{{data}});
        """)

    @noSourceTracking
    def append(self, item):
        JS("""    this['l'][this['l']['length']] = @{{item}};""")

    @noSourceTracking
    def extend(self, data):
        JS("""
        if (pyjslib['isArray'](@{{data}})) {
            var n = this['l']['length'];
            for (var i=0; i < @{{data}}['length']; i++) {
                this['l'][n+i]=@{{data}}[i];
                }
            }
        else if (pyjslib['isIteratable'](@{{data}})) {
            var iter=@{{data}}['__iter__']();
            var i=this['l']['length'];
            try {
                while (true) {
                    var item=iter['next']();
                    this['l'][i++]=item;
                    }
                }
            catch (e) {
                if (e['__name__'] != 'StopIteration') throw e;
                }
            }
        """)

    @noSourceTracking
    def remove(self, value):
        JS("""
        var index=this['index'](@{{value}});
        if (index<0) return false;
        this['l']['splice'](index, 1);
        return true;
        """)

    @noSourceTracking
    def index(self, value, start=0):
        JS("""
        var length=this['l']['length'];
        for (var i=@{{start}}; i<length; i++) {
            if (this['l'][i]==@{{value}}) {
                return i;
                }
            }
        return -1;
        """)

    @noSourceTracking
    def insert(self, index, value):
        JS("""    var a = this['l']; this['l']=a['slice'](0, @{{index}})['concat'](@{{value}}, a['slice'](@{{index}}));""")

    @noSourceTracking
    def pop(self, index = -1):
        JS("""
        if (@{{index}}<0) @{{index}} = this['l']['length'] + @{{index}};
        var a = this['l'][@{{index}}];
        this['l']['splice'](@{{index}}, 1);
        return a;
        """)

    @noSourceTracking
    def __cmp__(self, l):
        if not isinstance(l, List):
            return -1
        ll = len(self) - len(l)
        if ll != 0:
            return ll
        for x in range(len(l)):
            ll = cmp(self.__getitem__(x), l[x])
            if ll != 0:
                return ll
        return 0

    @noSourceTracking
    def slice(self, lower, upper):
        JS("""
        if (@{{upper}}==null) return pyjslib['List'](this['l']['slice'](@{{lower}}));
        return pyjslib['List'](this['l']['slice'](@{{lower}}, @{{upper}}));
        """)

    @noSourceTracking
    def __getitem__(self, index):
        JS("""
        if (@{{index}}<0) @{{index}} = this['l']['length'] + @{{index}};
        return this['l'][@{{index}}];
        """)

    @noSourceTracking
    def __setitem__(self, index, value):
        JS("""    this['l'][@{{index}}]=@{{value}};""")

    @noSourceTracking
    def __delitem__(self, index):
        JS("""    this['l']['splice'](@{{index}}, 1);""")

    @noSourceTracking
    def __len__(self):
        JS("""    return this['l']['length'];""")

    @noSourceTracking
    def __contains__(self, value):
        return self.index(value) >= 0

    @noSourceTracking
    def __iter__(self):
        JS("""
        var i = 0;
        var l = this['l'];
        return {
            'next': function() {
                if (i >= l['length']) {
                    throw pyjslib['StopIteration'];
                }
                return l[i++];
            },
            '__iter__': function() {
                return this;
            }
        };
        """)

    @noSourceTracking
    def reverse(self):
        JS("""    this['l']['reverse']();""")

    def sort(self, cmp=None, key=None, reverse=False):
        if not cmp:
            cmp = __cmp
        if key and reverse:
            def thisSort1(a,b):
                return -cmp(key(a), key(b))
            self.l.sort(thisSort1)
        elif key:
            def thisSort2(a,b):
                return cmp(key(a), key(b))
            self.l.sort(thisSort2)
        elif reverse:
            def thisSort3(a,b):
                return -cmp(a, b)
            self.l.sort(thisSort3)
        else:
            self.l.sort(cmp)

    @noSourceTracking
    def getArray(self):
        """
        Access the javascript Array that is used internally by this list
        """
        return self.l

    @noSourceTracking
    def __str__(self):
        return self.__repr__()

    @noSourceTracking
    def toString(self):
        return self.__repr__()

    def __repr__(self):
        #r = []
        #for item in self:
        #    r.append(repr(item))
        #return '[' + ', '.join(r) + ']'
        JS("""
        var s = "[";
        for (var i=0; i < @{{self}}['l']['length']; i++) {
            s += pyjslib['repr'](@{{self}}['l'][i]);
            if (i < @{{self}}['l']['length'] - 1)
                s += ", ";
        };
        s += "]"
        return s;
        """)

class Tuple:
    @noSourceTracking
    def __init__(self, data=None):
        JS("""
        this['l'] = [];
        this['extend'](@{{data}});
        """)

    @noSourceTracking
    def append(self, item):
        JS("""    this['l'][this['l']['length']] = @{{item}};""")

    @noSourceTracking
    def extend(self, data):
        JS("""
        if (pyjslib['isArray'](@{{data}})) {
            var n = this['l']['length'];
            for (var i=0; i < @{{data}}['length']; i++) {
                this['l'][n+i]=@{{data}}[i];
                }
            }
        else if (pyjslib['isIteratable'](@{{data}})) {
            var iter=@{{data}}['__iter__']();
            var i=this['l']['length'];
            try {
                while (true) {
                    var item=iter['next']();
                    this['l'][i++]=item;
                    }
                }
            catch (e) {
                if (e['__name__'] != 'StopIteration') throw e;
                }
            }
        """)

    @noSourceTracking
    def remove(self, value):
        JS("""
        var index=this['index'](@{{value}});
        if (index<0) return false;
        this['l']['splice'](index, 1);
        return true;
        """)

    @noSourceTracking
    def index(self, value, start=0):
        JS("""
        var length=this['l']['length'];
        for (var i=@{{start}}; i<length; i++) {
            if (this['l'][i]==@{{value}}) {
                return i;
                }
            }
        return -1;
        """)

    @noSourceTracking
    def insert(self, index, value):
        JS("""    var a = this['l']; this['l']=a['slice'](0, @{{index}})['concat'](@{{value}}, a['slice'](@{{index}}));""")

    @noSourceTracking
    def pop(self, index = -1):
        JS("""
        if (@{{index}}<0) @{{index}} = this['l']['length'] + @{{index}};
        var a = this['l'][@{{index}}];
        this['l']['splice'](@{{index}}, 1);
        return a;
        """)

    @noSourceTracking
    def __cmp__(self, l):
        if not isinstance(l, Tuple):
            return 1
        ll = len(self) - len(l)
        if ll != 0:
            return ll
        for x in range(len(l)):
            ll = cmp(self.__getitem__(x), l[x])
            if ll != 0:
                return ll
        return 0

    @noSourceTracking
    def slice(self, lower, upper):
        JS("""
        if (@{{upper}}==null) return pyjslib['Tuple'](this['l']['slice'](@{{lower}}));
        return pyjslib['Tuple'](this['l']['slice'](@{{lower}}, @{{upper}}));
        """)

    @noSourceTracking
    def __getitem__(self, index):
        JS("""
        if (@{{index}}<0) @{{index}} = this['l']['length'] + @{{index}};
        return this['l'][@{{index}}];
        """)

    @noSourceTracking
    def __setitem__(self, index, value):
        JS("""    this['l'][@{{index}}]=@{{value}};""")

    @noSourceTracking
    def __delitem__(self, index):
        JS("""    this['l']['splice'](@{{index}}, 1);""")

    @noSourceTracking
    def __len__(self):
        JS("""    return this['l']['length'];""")

    @noSourceTracking
    def __contains__(self, value):
        return self.index(value) >= 0

    @noSourceTracking
    def __iter__(self):
        JS("""
        var i = 0;
        var l = this['l'];
        return {
            'next': function() {
                if (i >= l['length']) {
                    throw pyjslib['StopIteration'];
                }
                return l[i++];
            },
            '__iter__': function() {
                return this;
            }
        };
        """)

    @noSourceTracking
    def reverse(self):
        JS("""    this['l']['reverse']();""")

    def sort(self, cmp=None, key=None, reverse=False):
        if not cmp:
            cmp = cmp
        if key and reverse:
            def thisSort1(a,b):
                return -cmp(key(a), key(b))
            self.l.sort(thisSort1)
        elif key:
            def thisSort2(a,b):
                return cmp(key(a), key(b))
            self.l.sort(thisSort2)
        elif reverse:
            def thisSort3(a,b):
                return -cmp(a, b)
            self.l.sort(thisSort3)
        else:
            self.l.sort(cmp)

    @noSourceTracking
    def getArray(self):
        """
        Access the javascript Array that is used internally by this list
        """
        return self.l

    @noSourceTracking
    def __str__(self):
        return self.__repr__()

    @noSourceTracking
    def toString(self):
        return self.__repr__()

    def __repr__(self):
        #r = []
        #for item in self:
        #    r.append(repr(item))
        #if len(r) == 1:
        #    return '(' + ', '.join(r) + ',)'
        #return '(' + ', '.join(r) + ')'
        JS("""
        var s = "(";
        for (var i=0; i < @{{self}}['l']['length']; i++) {
            s += pyjslib['repr'](@{{self}}['l'][i]);
            if (i < @{{self}}['l']['length'] - 1)
                s += ", ";
        };
        if (@{{self}}['l']['length'] == 1)
            s += ",";
        s += ")"
        return s;
        """)

class Dict:
    @noSourceTracking
    def __init__(self, data=None):
        JS("""
        this['d'] = {};

        if (pyjslib['isArray'](@{{data}})) {
            for (var i in @{{data}}) {
                var item=@{{data}}[i];
                this['__setitem__'](item[0], item[1]);
                //var sKey=pyjslib['hash'](item[0]);
                //this['d'][sKey]=item[1];
                }
            }
        else if (pyjslib['isIteratable'](@{{data}})) {
            var iter=@{{data}}['__iter__']();
            try {
                while (true) {
                    var item=iter['next']();
                    this['__setitem__'](item['__getitem__'](0), item['__getitem__'](1));
                    }
                }
            catch (e) {
                if (e['__name__'] != 'StopIteration') throw e;
                }
            }
        else if (pyjslib['isObject'](@{{data}})) {
            for (var key in @{{data}}) {
                this['__setitem__'](key, @{{data}}[key]);
                }
            }
        """)

    @noSourceTracking
    def __setitem__(self, key, value):
        JS("""
        var sKey = pyjslib['hash'](@{{key}});
        this['d'][sKey]=[@{{key}}, @{{value}}];
        """)

    @noSourceTracking
    def __getitem__(self, key):
        JS("""
        var sKey = pyjslib['hash'](@{{key}});
        var value=this['d'][sKey];
        if (pyjslib['isUndefined'](value)){
            throw pyjslib['KeyError'](@{{key}});
        }
        return value[1];
        """)

    @noSourceTracking
    def __nonzero__(self):
        JS("""
        for (var i in this['d']){
            return true;
        }
        return false;
        """)

    @noSourceTracking
    def __len__(self):
        JS("""
        var size=0;
        for (var i in this['d']) size++;
        return size;
        """)

    @noSourceTracking
    def has_key(self, key):
        return self.__contains__(key)

    @noSourceTracking
    def __delitem__(self, key):
        JS("""
        var sKey = pyjslib['hash'](@{{key}});
        delete this['d'][sKey];
        """)

    @noSourceTracking
    def __contains__(self, key):
        JS("""
        var sKey = pyjslib['hash'](@{{key}});
        return (pyjslib['isUndefined'](this['d'][sKey])) ? false : true;
        """)

    @noSourceTracking
    def keys(self):
        JS("""
        var keys=new pyjslib['List']();
        for (var key in this['d']) {
            keys['append'](this['d'][key][0]);
        }
        return keys;
        """)

    @noSourceTracking
    def values(self):
        JS("""
        var values=new pyjslib['List']();
        for (var key in this['d']) values['append'](this['d'][key][1]);
        return values;
        """)

    @noSourceTracking
    def items(self):
        JS("""
        var items = new pyjslib['List']();
        for (var key in this['d']) {
          var kv = this['d'][key];
          items['append'](new pyjslib['List'](kv))
          }
          return items;
        """)

    @noSourceTracking
    def __iter__(self):
        return self.keys().__iter__()

    @noSourceTracking
    def iterkeys(self):
        return self.__iter__()

    @noSourceTracking
    def itervalues(self):
        return self.values().__iter__();

    @noSourceTracking
    def iteritems(self):
        return self.items().__iter__();

    @noSourceTracking
    def setdefault(self, key, default_value):
        if not self.has_key(key):
            self[key] = default_value
        return self[key]

    @noSourceTracking
    def get(self, key, default_value=None):
        if not self.has_key(key):
            return default_value
        return self[key]

    @noSourceTracking
    def update(self, d):
        for k,v in d.iteritems():
            self[k] = v

    @noSourceTracking
    def getObject(self):
        """
        Return the javascript Object which this class uses to store
        dictionary keys and values
        """
        return self.d

    @noSourceTracking
    def copy(self):
        return Dict(self.items())

    @noSourceTracking
    def __str__(self):
        return self.__repr__()

    @noSourceTracking
    def toString(self):
        return self.__repr__()

    def __repr__(self):
        #r = []
        #for item in self:
        #    r.append(repr(item) + ': ' + repr(self[item]))
        #return '{' + ', '.join(r) + '}'
        JS("""
        var keys = new Array();
        for (var key in @{{self}}['d'])
            keys['push'](key);

        var s = "{";
        for (var i=0; i<keys['length']; i++) {
            var v = @{{self}}['d'][keys[i]]
            s += pyjslib['repr'](v[0]) + ": " + pyjslib['repr'](v[1]);
            if (i < keys['length']-1)
                s += ", "
        };
        s += "}";
        return s;
        """)

# IE6 doesn't like pyjslib.super
@noSourceTracking
def _super(type_, object_or_type = None):
    # This is a partially implementation: only super(type, object)
    if not _issubtype(object_or_type, type_):
        raise TypeError("super(type, obj): obj must be an instance or subtype of type")
    JS("""
    var fn = pyjs_type('super', @{{type_}}['__mro__']['slice'](1), {})
    fn['__new__'] = fn['__mro__'][1]['__new__'];
    fn['__init__'] = fn['__mro__'][1]['__init__'];
    if (@{{object_or_type}}['__is_instance__'] === false) {
        return fn;
    }
    var obj = new Object();
    function wrapper(obj, name) {
        var fnwrap = function() {
            var args = [];
            for (var i = 0; i < arguments['length']; i++) {
              args['push'](arguments[i]);
            }
            return obj[name]['apply'](@{{object_or_type}},args);
        }
        fnwrap['__name__'] = name;
        fnwrap['parse_kwargs'] = obj['parse_kwargs'];
        return fnwrap;
    }
    for (var m in fn) {
        if (typeof fn[m] == 'function') {
            obj[m] = wrapper(fn, m);
        }
    }
    return obj;
    """)

# taken from mochikit: range( [start,] stop[, step] )
@noSourceTracking
def range(start, stop = None, step = 1):
    if stop is None:
        stop = start
        start = 0
    JS("""
/*
    var start = 0;
    var stop = 0;
    var step = 1;

    if (arguments['length'] == 2) {
        start = arguments[0];
        stop = arguments[1];
        }
    else if (arguments['length'] == 3) {
        start = arguments[0];
        stop = arguments[1];
        step = arguments[2];
        }
    else if (arguments['length']>0) stop = arguments[0];
*/
    return {
        'next': function() {
            if ((@{{step}} > 0 && @{{start}} >= @{{stop}}) || (@{{step}} < 0 && @{{start}} <= @{{stop}})) throw pyjslib['StopIteration'];
            var rval = @{{start}};
            @{{start}} += @{{step}};
            return rval;
            },
        '__iter__': function() {
            return this;
            }
        }
    """)

@noSourceTracking
def slice(object, lower, upper):
    JS("""
    if (pyjslib['isString'](object)) {
        if (@{{lower}} < 0) {
           @{{lower}} = object['length'] + @{{lower}};
        }
        if (@{{upper}} < 0) {
           @{{upper}} = object['length'] + @{{upper}};
        }
        if (pyjslib['isNull'](@{{upper}})) @{{upper}}=object['length'];
        return object['substring'](@{{lower}}, @{{upper}});
    }
    if (pyjslib['isObject'](object) && object['slice'])
        return object['slice'](@{{lower}}, @{{upper}});

    return null;
    """)

@noSourceTracking
def str(text):
    JS("""
    if (pyjslib['hasattr'](@{{text}},"__str__")) {
        return @{{text}}['__str__']();
    }
    return String(@{{text}});
    """)

@noSourceTracking
def ord(x):
    if(isString(x) and len(x) is 1):
        JS("""
            return @{{x}}['charCodeAt'](0);
        """)
    else:
        JS("""
            throw pyjslib['TypeError']();
        """)
    return None

@noSourceTracking
def chr(x):
    JS("""
        return String['fromCharCode'](@{{x}})
    """)

@noSourceTracking
def is_basetype(x):
    JS("""
       var t = typeof(@{{x}});
       return t == 'boolean' ||
       t == 'function' ||
       t == 'number' ||
       t == 'string' ||
       t == 'undefined'
       ;
    """)

@noSourceTracking
def get_pyjs_classtype(x):
    JS("""
        if (pyjslib['hasattr'](@{{x}}, "__is_instance__")) {
            var src = @{{x}}['__name__'];
            return src;
        }
        return null;
    """)

@noSourceTracking
def repr(x):
    """ Return the string representation of 'x'.
    """
    if hasattr(x, '__repr__'):
        return x.__repr__()
    JS("""
       if (@{{x}} === null)
           return "null";

       if (@{{x}} === undefined)
           return "undefined";

       var t = typeof(@{{x}});

        //alert("repr typeof " + t + " : " + xXXX);

       if (t == "boolean")
           return @{{x}}['toString']();

       if (t == "function")
           return "<function " + @{{x}}['toString']() + ">";

       if (t == "number")
           return @{{x}}['toString']();

       if (t == "string") {
           if (@{{x}}['indexOf']("'") == -1)
               return "'" + @{{x}} + "'";
           if (@{{x}}['indexOf']('"') == -1)
               return '"' + @{{x}} + '"';
           var s = @{{x}}['replace'](new RegExp('"', "g"), '\\\\"');
           return '"' + s + '"';
       };

       if (t == "undefined")
           return "undefined";

       // If we get here, x is an object.  See if it's a Pyjamas class.

       if (!pyjslib['hasattr'](@{{x}}, "__init__"))
           return "<" + @{{x}}['toString']() + ">";

       // Handle the common Pyjamas data types.

       var constructor = "UNKNOWN";

       constructor = pyjslib['get_pyjs_classtype'](@{{x}});

        //alert("repr constructor: " + constructor);

       // If we get here, the class isn't one we know -> return the class name.
       // Note that we replace underscores with dots so that the name will
       // (hopefully!) look like the original Python name.

       //var s = constructor['replace'](new RegExp('_', "g"), '.');
       return "<" + constructor + " object>";
    """)

@noSourceTracking
def float(text):
    JS("""
    return parseFloat(@{{text}});
    """)

@noSourceTracking
def int(text, radix=0):
    JS("""
    var i = parseInt(@{{text}}, @{{radix}});
    if (!isNaN(i)) {
        return i;
    }
    """)
    if radix == 0:
        radix = 10
    raise ValueError("invalid literal for int() with base %d: '%s'" % (radix, text))

@noSourceTracking
def len(object):
    JS("""
    if (object==null) return 0;
    if (pyjslib['isObject'](object) && object['__len__']) return object['__len__']();
    return object['length'];
    """)

@noSourceTracking
def isinstance(object_, classinfo):
    if pyjslib.isUndefined(object_):
        return False
    JS("""if (@{{classinfo}}['__name__'] == 'int') {
            return pyjslib['isNumber'](@{{object_}}); /* XXX TODO: check rounded? */
            }
        """)
    JS("""if (@{{classinfo}}['__name__'] == 'str') {
            return pyjslib['isString'](@{{object_}});
            }
        """)
    if not pyjslib.isObject(object_):
        return False
    if _isinstance(classinfo, Tuple):
        for ci in classinfo:
            if isinstance(object_, ci):
                return True
        return False
    else:
        return _isinstance(object_, classinfo)

@noSourceTracking
def _isinstance(object_, classinfo):
    JS("""
    if (@{{object_}}['__is_instance__'] !== true) {
        return false;
    }
    for (var c in @{{object_}}['__mro__']) {
        if (@{{object_}}['__mro__'][c]['__md5__'] == @{{classinfo}}['prototype']['__md5__']) return true;
    }
    return false;
    """)

@noSourceTracking
def _issubtype(object_, classinfo):
    JS("""
    if (@{{object_}}['__is_instance__'] == null || @{{classinfo}}['__is_instance__'] == null) {
        return false;
    }
    for (var c in @{{object_}}['__mro__']) {
        if (@{{object_}}['__mro__'][c] == @{{classinfo}}['prototype']) return true;
    }
    return false;
    """)

@noSourceTracking
def getattr(obj, name, default_value=None):
    JS("""
    if ((!pyjslib['isObject'](@{{obj}}))||(pyjslib['isUndefined'](@{{obj}}[@{{name}}]))){
        if (arguments['length'] != 3){
            throw pyjslib['AttributeError'](@{{obj}}, @{{name}});
        }else{
        return @{{default_value}};
        }
    }
    if (!pyjslib['isFunction'](@{{obj}}[@{{name}}])) return @{{obj}}[@{{name}}];
    var method = @{{obj}}[@{{name}}];
    var fnwrap = function() {
        var args = [];
        for (var i = 0; i < arguments['length']; i++) {
          args['push'](arguments[i]);
        }
        return method['apply'](@{{obj}},args);
    }
    fnwrap['__name__'] = @{{name}};
    fnwrap['parse_kwargs'] = @{{obj}}['parse_kwargs'];
    return fnwrap;
    """)

@noSourceTracking
def delattr(obj, name):
    JS("""
    if (!pyjslib['isObject'](@{{obj}})) {
       throw pyjslib['AttributeError']("'"+typeof(@{{obj}})+"' object has no attribute '"+@{{name}}+"%s'")
    }
    if ((pyjslib['isUndefined'](@{{obj}}[@{{name}}])) ||(typeof(@{{obj}}[@{{name}}]) == "function") ){
        throw pyjslib['AttributeError'](@{{obj}}['__name__']+" instance has no attribute '"+ @{{name}}+"'");
    }
    delete @{{obj}}[@{{name}}];
    """)

@noSourceTracking
def setattr(obj, name, value):
    JS("""
    if (!pyjslib['isObject'](@{{obj}})) return null;

    @{{obj}}[@{{name}}] = @{{value}};

    """)

@noSourceTracking
def hasattr(obj, name):
    JS("""
    if (!pyjslib['isObject'](@{{obj}})) return false;
    if (pyjslib['isUndefined'](@{{obj}}[@{{name}}])) return false;

    return true;
    """)

@noSourceTracking
def dir(obj):
    JS("""
    var properties=new pyjslib['List']();
    for (property in @{{obj}}) properties['append'](property);
    return properties;
    """)

@noSourceTracking
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


@noSourceTracking
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


def enumerate(sequence):
    enumeration = []
    nextIndex = 0
    for item in sequence:
        enumeration.append([nextIndex, item])
        nextIndex = nextIndex + 1
    return enumeration


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


@noSourceTracking
def hash(obj):
    JS("""
    if (@{{obj}} == null) return null;

    if (@{{obj}}['$H']) return @{{obj}}['$H'];
    if (@{{obj}}['__hash__']) return @{{obj}}['__hash__']();
    if (@{{obj}}['constructor'] == String || @{{obj}}['constructor'] == Number || @{{obj}}['constructor'] == Date) return @{{obj}};

    @{{obj}}['$H'] = ++pyjslib['next_hash_id'];
    return @{{obj}}['$H'];
    """)


# type functions from Douglas Crockford's Remedial Javascript: http://www.crockford.com/javascript/remedial.html
@noSourceTracking
def isObject(a):
    JS("""
    return (@{{a}} != null && (typeof @{{a}} == 'object')) || pyjslib['isFunction'](@{{a}});
    """)

@noSourceTracking
def isFunction(a):
    JS("""
    return typeof @{{a}} == 'function';
    """)

@noSourceTracking
def isString(a):
    JS("""
    return typeof @{{a}} == 'string';
    """)

@noSourceTracking
def isNull(a):
    JS("""
    return typeof @{{a}} == 'object' && !@{{a}};
    """)

@noSourceTracking
def isArray(a):
    JS("""
    return pyjslib['isObject'](@{{a}}) && @{{a}}['constructor'] == Array;
    """)

@noSourceTracking
def isUndefined(a):
    JS("""
    return typeof @{{a}} == 'undefined';
    """)

@noSourceTracking
def isIteratable(a):
    JS("""
    return pyjslib['isString'](@{{a}}) || (pyjslib['isObject'](@{{a}}) && @{{a}}['__iter__']);
    """)

@noSourceTracking
def isNumber(a):
    JS("""
    return typeof @{{a}} == 'number' && isFinite(@{{a}});
    """)

@noSourceTracking
def toJSObjects(x):
    """
       Convert the pyjs pythonic List and Dict objects into javascript Object and Array
       objects, recursively.
    """
    if isArray(x):
        JS("""
        var result = [];
        for(var k=0; k < @{{x}}['length']; k++) {
           var v = @{{x}}[k];
           var tv = pyjslib['toJSObjects'](v);
           result['push'](tv);
        }
        return result;
        """)
    if isObject(x):
        if isinstance(x, Dict):
            JS("""
            var o = @{{x}}['getObject']();
            var result = {};
            for (var i in o) {
               result[o[i][0]['toString']()] = o[i][1];
            }
            return pyjslib['toJSObjects'](result)
            """)
        elif isinstance(x, List):
            return toJSObjects(x.l)
        elif hasattr(x, '__class__'):
            # we do not have a special implementation for custom
            # classes, just pass it on
            return x
    if isObject(x):
        JS("""
        var result = {};
        for(var k in @{{x}}) {
            var v = @{{x}}[k];
            var tv = pyjslib['toJSObjects'](v)
            result[k] = tv;
            }
            return result;
         """)
    return x

@noSourceTracking
def sprintf(strng, args):
    # See http://docs.python.org/library/stdtypes.html
    constructor = get_pyjs_classtype(args)
    JS("""
    var re_dict = /([^%]*)%[(]([^)]+)[)]([#0\x20\0x2B-]*)(\d+)?(\.\d+)?[hlL]?(.)((.|\\n)*)/;
    var re_list = /([^%]*)%([#0\x20\x2B-]*)(\*|(\d+))?(\.\d+)?[hlL]?(.)((.|\\n)*)/;
    var re_exp = /(.*)([+-])(.*)/;
""")
    strlen = len(strng)
    argidx = 0
    nargs = 0
    result = []
    remainder = strng

    def next_arg():
        if argidx == nargs:
            raise TypeError("not enough arguments for format string")
        arg = args[argidx]
        argidx += 1
        return arg

    def formatarg(flags, minlen, precision, conversion, param):
            subst = ''
            numeric = True
            if not minlen:
                minlen=0
            else:
                minlen = int(minlen)
            if not precision:
                precision = None
            else:
                precision = int(precision)
            left_padding = 1
            if flags.find('-') >= 0:
                left_padding = 0
            if conversion == '%':
                numeric = False
                subst = '%'
            elif conversion == 'c':
                numeric = False
                subst = chr(int(param))
            elif conversion == 'd' or conversion == 'i' or conversion == 'u':
                subst = str(int(param))
            elif conversion == 'e':
                if precision is None:
                    precision = 6
                JS("""
                @{{subst}} = @{{!re_exp}}['exec'](String(@{{param}}['toExponential'](@{{precision}})));
                if (@{{subst}}[3]['length'] == 1) {
                    @{{subst}} = @{{subst}}[1] + @{{subst}}[2] + '0' + @{{subst}}[3];
                } else {
                    @{{subst}} = @{{subst}}[1] + @{{subst}}[2] + @{{subst}}[3];
                }""")
            elif conversion == 'E':
                if precision is None:
                    precision = 6
                JS("""
                @{{subst}} = @{{!re_exp}}['exec'](String(@{{param}}['toExponential'](@{{precision}}))['toUpperCase']());
                if (@{{subst}}[3]['length'] == 1) {
                    @{{subst}} = @{{subst}}[1] + @{{subst}}[2] + '0' + @{{subst}}[3];
                } else {
                    @{{subst}} = @{{subst}}[1] + @{{subst}}[2] + @{{subst}}[3];
                }""")
            elif conversion == 'f':
                if precision is None:
                    precision = 6
                JS("""
                @{{subst}} = String(parseFloat(@{{param}})['toFixed'](@{{precision}}));""")
            elif conversion == 'F':
                if precision is None:
                    precision = 6
                JS("""
                @{{subst}} = String(parseFloat(@{{param}})['toFixed'](@{{precision}}))['toUpperCase']();""")
            elif conversion == 'g':
                if flags.find('#') >= 0:
                    if precision is None:
                        precision = 6
                if param >= 1E6 or param < 1E-5:
                    JS("""
                    @{{subst}} = String(@{{precision}} == null ? @{{param}}['toExponential']() : @{{param}}['toExponential']()['toPrecision'](@{{precision}}));""")
                else:
                    JS("""
                    @{{subst}} = String(@{{precision}} == null ? parseFloat(@{{param}}) : parseFloat(@{{param}})['toPrecision'](@{{precision}}));""")
            elif conversion == 'G':
                if flags.find('#') >= 0:
                    if precision is None:
                        precision = 6
                if param >= 1E6 or param < 1E-5:
                    JS("""
                    @{{subst}} = String(@{{precision}} == null ? @{{param}}['toExponential']() : @{{param}}['toExponential']()['toPrecision'](@{{precision}}))['toUpperCase']();""")
                else:
                    JS("""
                    @{{subst}} = String(@{{precision}} == null ? parseFloat(@{{param}}) : parseFloat(@{{param}})['toPrecision'](@{{precision}}))['toUpperCase']()['toUpperCase']();""")
            elif conversion == 'r':
                numeric = False
                subst = repr(param)
            elif conversion == 's':
                numeric = False
                subst = str(param)
            elif conversion == 'o':
                param = int(param)
                JS("""
                @{{subst}} = @{{param}}['toString'](8);""")
                if flags.find('#') >= 0 and subst != '0':
                    subst = '0' + subst
            elif conversion == 'x':
                param = int(param)
                JS("""
                @{{subst}} = @{{param}}['toString'](16);""")
                if flags.find('#') >= 0:
                    if left_padding:
                        subst = subst.rjust(minlen - 2, '0')
                    subst = '0x' + subst
            elif conversion == 'X':
                param = int(param)
                JS("""
                @{{subst}} = @{{param}}['toString'](16)['toUpperCase']();""")
                if flags.find('#') >= 0:
                    if left_padding:
                        subst = subst.rjust(minlen - 2, '0')
                    subst = '0X' + subst
            else:
                raise ValueError("unsupported format character '" + conversion + "' ("+hex(ord(conversion))+") at index " + (strlen - len(remainder) - 1))
            if minlen and len(subst) < minlen:
                padchar = ' '
                if numeric and left_padding and flags.find('0') >= 0:
                    padchar = '0'
                if left_padding:
                    subst = subst.rjust(minlen, padchar)
                else:
                    subst = subst.ljust(minlen, padchar)
            return subst

    def sprintf_list(strng, args):
        while remainder:
            JS("""
            var a = @{{!re_list}}['exec'](@{{remainder}});""")
            if a is None:
                result.append(remainder)
                break;
            JS("""
            var left = @{{!a}}[1], flags = @{{!a}}[2];
            var minlen = @{{!a}}[3], precision = @{{!a}}[5], conversion = @{{!a}}[6];
            @{{remainder}} = @{{!a}}[7];
            if (typeof minlen == 'undefined') minlen = null;
            if (typeof precision == 'undefined') precision = null;
            if (typeof conversion == 'undefined') conversion = null;
""")
            result.append(left)
            if minlen == '*':
                minlen = next_arg()
                JS("var minlen_type = typeof(@{{minlen}});")
                if minlen_type != 'number' or \
                   int(minlen) != minlen:
                    raise TypeError('* wants int')
            if conversion != '%':
                param = next_arg()
            result.append(formatarg(flags, minlen, precision, conversion, param))

    def sprintf_dict(strng, args):
        arg = args
        argidx += 1
        while remainder:
            JS("""
            var a = @{{!re_dict}}['exec'](@{{remainder}});""")
            if a is None:
                result.append(remainder)
                break;
            JS("""
            var left = @{{!a}}[1], key = @{{!a}}[2], flags = @{{!a}}[3];
            var minlen = @{{!a}}[4], precision = @{{!a}}[5], conversion = @{{!a}}[6];
            @{{remainder}} = @{{!a}}[7];
            if (typeof minlen == 'undefined') minlen = null;
            if (typeof precision == 'undefined') precision = null;
            if (typeof conversion == 'undefined') conversion = null;
""")
            result.append(left)
            if not arg.has_key(key):
                raise KeyError(key)
            else:
                param = arg[key]
            result.append(formatarg(flags, minlen, precision, conversion, param))

    JS("""
    var a = @{{!re_dict}}['exec'](@{{strng}});
""")
    if a is None:
        if constructor != "Tuple":
            args = (args,)
        nargs = len(args)
        sprintf_list(strng, args)
        if argidx != nargs:
            raise TypeError('not all arguments converted during string formatting')
    else:
        if constructor != "Dict":
            raise TypeError("format requires a mapping")
        sprintf_dict(strng, args)
    return ''.join(result)

@noSourceTracking
def printFunc(objs, newline):
    JS("""
    if ($wnd['console']==undefined)  return;
    var s = "";
    for(var i=0; i < @{{objs}}['length']; i++) {
        if(s != "") s += " ";
        s += @{{objs}}[i];
    }
    console['debug'](s)
    """)

@noSourceTracking
def type(clsname, bases=None, methods=None):
    """ creates a class, derived from bases, with methods and variables
    """

    JS(" var mths = {}; ")
    if methods:
        for k in methods.keys():
            mth = methods[k]
            JS(" @{{mths}}[@{{k}}] = @{{mth}}; ")

    JS(" var bss = null; ")
    if bases:
        JS("@{{bss}} = @{{bases}}['l'];")
    JS(" return pyjs_type(@{{clsname}}, @{{bss}}, @{{mths}}); ")

def pow(x, y, z = None):
    JS("@{{p}} = Math['pow'](@{{x}}, @{{y}});")
    if z is None:
        return float(p)
    return float(p % z)

def hex(x):
    if int(x) != x:
        raise TypeError("hex() argument can't be converted to hex")
    JS("@{{r}} = '0x'+@{{x}}['toString'](16);")
    return str(r)

def oct(x):
    if int(x) != x:
        raise TypeError("oct() argument can't be converted to oct")
    JS("@{{r}} = '0'+@{{x}}['toString'](8);")
    return str(r)

def round(x, n = 0):
    n = pow(10, n)
    JS("@{{r}} = Math['round'](@{{n}}*@{{x}})/@{{n}};")
    return float(r)

def divmod(x, y):
    if int(x) == x and int(y) == y:
        return (int(x / y), int(x % y))
    JS("@{{f}} = Math['floor'](@{{x}} / @{{y}});")
    f = float(f)
    return (f, x - f * y)

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
