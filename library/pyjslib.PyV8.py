# pyv8_print_fn is actually in pyv8run.py and is added to the Globals
def printFunc(objs, newline):
    JS("""
        var s = "";
        for(var i=0; i < @{{objs}}['length']; i++) {
            if(s != "") s += " ";
                s += @{{objs}}[i];
        }

        @{{pyv8_print_fn}}(s);
    """)

# pyv8_import_module is actually in pyv8run.py and has been added to Globals.
def import_module(syspath, parent_name, module_name, dynamic_load, async, init):
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
        if not isUndefined(module):
            # Not initialized, but present. Must be pyjs module.
            if JS("@{{module}}['__was_initialized__'] != true"):
                # Module wasn't initialized
                module()
        else:
            # Get a pytjon module from PyV8
            initialized = False
            try:
                JS("@{{initialized}} = (@{{module}}['__was_initialized__'] != true)")
            except:
                pass
            if not initialized:
                # Module wasn't initialized
                module = pyv8_import_module(parent_name, module_name)
                module.__was_initialized__ = True
                JS("""$pyjs['modules_hash'][@{{importName}}] = @{{module}}""")
        importName += '.'
    name = names[0]
    JS("""$pyjs['modules'][@{{name}}] = $pyjs['modules_hash'][@{{name}}];""")
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

        //alert("cache " + cache_file + " " + module_nameXXX + " " + parent_moduleXXX);

        var onload_fn = '';

        // this one tacks the script onto the end of the DOM
        @{{pyjs_load_script}}(cache_file, onload_fn, @{{async}});

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

# There seems to be an bug in Chrome with accessing the message
# property, on which an error is thrown
# Hence the declaration of 'var message' and the wrapping in try..catch
def init():
    JS("""
@{{_errorMapping}} = function(err) {
    if (err instanceof(ReferenceError) || err instanceof(TypeError)) {
        var message = ''
        try {
            message = err['message'];
        } catch ( e) {
        }
        return @{{AttributeError}}(message);
    }
    return err
}

@{{TryElse}} = function () { };
@{{TryElse}}['prototype'] = new Error();
@{{TryElse}}['__name__'] = 'TryElse';
@{{TryElse}}['message'] = 'TryElse';

@{{StopIteration}} = function () { };
@{{StopIteration}}['prototype'] = new Error();
@{{StopIteration}}['__name__'] = 'StopIteration';
@{{StopIteration}}['message'] = 'StopIteration';

@{{String_find}} = function(sub, start, end) {
    var pos=this['indexOf'](sub, start);
    if (@{{isUndefined}}(end)) return pos;

    if (pos + sub['length']>end) return -1;
    return pos;
}

@{{String_join}} = function(data) {
    var text="";

    if (@{{isArray}}(data)) {
        return data['join'](this);
    }
    else if (@{{isIteratable}}(data)) {
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

@{{String_isdigit}} = function() {
    return (this['match'](/^\d+$/g) != null);
}

@{{String_replace}} = function(old, replace, count) {
    var do_max=false;
    var start=0;
    var new_str="";
    var pos=0;

    if (!@{{isString}}(old)) return this['__replace'](old, replace);
    if (!@{{isUndefined}}(count)) do_max=true;

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

@{{String_split}} = function(sep, maxsplit) {
    var items=new @{{List}}();
    var do_max=false;
    var subject=this;
    var start=0;
    var pos=0;

    if (@{{isUndefined}}(sep) || @{{isNull}}(sep)) {
        sep=" ";
        subject=subject['strip']();
        subject=subject['replace'](/\s+/g, sep);
    }
    else if (!@{{isUndefined}}(maxsplit)) do_max=true;

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

@{{String___iter__}} = function() {
    var i = 0;
    var s = this;
    return {
        'next': function() {
            if (i >= s['length']) {
                throw @{{StopIteration}};
            }
            return s['substring'](i++, i, 1);
        },
        '__iter__': function() {
            return this;
        }
    };
}

@{{String_strip}} = function(chars) {
    return this['lstrip'](chars)['rstrip'](chars);
}

@{{String_lstrip}} = function(chars) {
    if (@{{isUndefined}}(chars)) return this['replace'](/^\s+/, "");

    return this['replace'](new RegExp("^[" + chars + "]+"), "");
}

@{{String_rstrip}} = function(chars) {
    if (@{{isUndefined}}(chars)) return this['replace'](/\s+$/, "");

    return this['replace'](new RegExp("[" + chars + "]+$"), "");
}

@{{String_startswith}} = function(prefix, start, end) {
    // FIXME: accept tuples as suffix (since 2['5'])
    if (@{{isUndefined}}(start)) start = 0;
    if (@{{isUndefined}}(end)) end = this['length'];

    if ((end - start) < prefix['length']) return false
    if (this['substr'](start, prefix['length']) == prefix) return true;
    return false;
}

@{{String_endswith}} = function(suffix, start, end) {
    // FIXME: accept tuples as suffix (since 2['5'])
    if (@{{isUndefined}}(start)) start = 0;
    if (@{{isUndefined}}(end)) end = this['length'];

    if ((end - start) < suffix['length']) return false
    if (this['substr'](end - suffix['length'], suffix['length']) == suffix) return true;
    return false;
}

@{{String_ljust}} = function(width, fillchar) {
    if (typeof(width) != 'number' ||
        parseInt(width) != width) {
        throw (@{{TypeError}}("an integer is required"));
    }
    if (@{{isUndefined}}(fillchar)) fillchar = ' ';
    if (typeof(fillchar) != 'string' ||
        fillchar['length'] != 1) {
        throw (@{{TypeError}}("ljust() argument 2 must be char, not " + typeof(fillchar)));
    }
    if (this['length'] >= width) return this;
    return this + new Array(width+1 - this['length'])['join'](fillchar);
}

@{{String_rjust}} = function(width, fillchar) {
    if (typeof(width) != 'number' ||
        parseInt(width) != width) {
        throw (@{{TypeError}}("an integer is required"));
    }
    if (@{{isUndefined}}(fillchar)) fillchar = ' ';
    if (typeof(fillchar) != 'string' ||
        fillchar['length'] != 1) {
        throw (@{{TypeError}}("rjust() argument 2 must be char, not " + typeof(fillchar)));
    }
    if (this['length'] >= width) return this;
    return new Array(width + 1 - this['length'])['join'](fillchar) + this;
}

@{{String_center}} = function(width, fillchar) {
    if (typeof(width) != 'number' ||
        parseInt(width) != width) {
        throw (@{{TypeError}}("an integer is required"));
    }
    if (@{{isUndefined}}(fillchar)) fillchar = ' ';
    if (typeof(fillchar) != 'string' ||
        fillchar['length'] != 1) {
        throw (@{{TypeError}}("center() argument 2 must be char, not " + typeof(fillchar)));
    }
    if (this['length'] >= width) return this;
    var padlen = width - this['length'];
    var right = Math['ceil'](padlen / 2);
    var left = padlen - right;
    return new Array(left+1)['join'](fillchar) + this + new Array(right+1)['join'](fillchar);
}

@{{abs}} = Math['abs'];

""")
