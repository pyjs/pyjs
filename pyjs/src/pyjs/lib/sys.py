from __pyjamas__ import JS

# a dictionary of module override names (platform-specific)
overrides = None # to be updated by app, on compile

# the remote path for loading modules
loadpath = None

stacktrace = None

appname = None

version_info = (2, 7, 2, 'pyjamas', 0)
subversion = ('Pyjamas', '', '')

path = []
argv = []

platform = JS('$pyjs["platform"]')
byteorder = 'little' # Needed in struct.py, assume all systems are little endian and not big endian
maxint = 2147483647  # javascript bit operations are on 32 bit signed numbers


def setloadpath(lp):
    global loadpath
    loadpath = lp

def setappname(an):
    global appname
    appname = an

def getloadpath():
    return loadpath

def addoverride(module_name, path):
    overrides[module_name] = path

def exc_info():
    le = JS('$pyjs["__last_exception__"]')
    if not le:
        return (None, None, None)
    if not hasattr(le.error, '__class__'):
        cls = None
    else:
        cls = le.error.__class__
    tb = JS('$pyjs["__last_exception_stack__"]')
    if tb:
        start = tb.start
        while tb and start > 0:
            tb = tb.tb_next
            start -= 1
    return (cls, le.error, tb)

def exc_clear():
    JS('$pyjs["__last_exception_stack__"] = $pyjs["__last_exception__"] = null;')

# save_exception_stack is totally javascript, to prevent trackstack pollution
JS("""@{{_exception_from_trackstack}} = function (trackstack, start) {
    if (typeof start == 'undefined') {
      start = 0;
    }
    var exception_stack = null;
    var top = null;
    for (var needle=0; needle < $pyjs['trackstack']['length']; needle++) {
        var t = new Object();
        for (var p in $pyjs['trackstack'][needle]) {
            t[p] = $pyjs['trackstack'][needle][p];
        }
        if (typeof $pyjs['loaded_modules'][t['module']]['__track_lines__'] != 'undefined') {
          var f_globals = $p['dict']();
          for (var name in $pyjs['loaded_modules'][t['module']]) {
            f_globals['__setitem__'](name, $pyjs['loaded_modules'][t['module']][name]);
          }
          t['tb_frame'] = {'f_globals': f_globals};
        }
        if (exception_stack == null) {
            exception_stack = top = t;
        } else {
          top['tb_next'] = t;
        }
        top = t;
    }
    top['tb_next'] = null;
    exception_stack['start'] = start;
    return exception_stack;
};""")

JS("""@{{save_exception_stack}} = function (start) {
    if ($pyjs['__active_exception_stack__']) {
        $pyjs['__active_exception_stack__']['start'] = start;
        return $pyjs['__active_exception_stack__'];
    }
    $pyjs['__active_exception_stack__'] = @{{_exception_from_trackstack}}($pyjs['trackstack'], start);
    return $pyjs['__active_exception_stack__'];
};""")

def trackstacklist(stack=None, limit=None):
    if stack is None:
        stack = JS('$pyjs["__active_exception_stack__"]')
    else:
        if JS("""@{{stack}} instanceof Array"""):
            stack = _exception_from_trackstack(stack)
    if stack is None:
        return ''
    stackstrings = []
    msg = ''
    if limit is None:
        limit = -1
    while stack and limit:
        JS("@{{msg}} = $pyjs['loaded_modules'][@{{stack}}['module']]['__track_lines__'][@{{stack}}['lineno']];")
        JS("if (typeof @{{msg}} == 'undefined') @{{msg}} = null;")
        if msg:
            stackstrings.append(msg + '\n')
        else:
            stackstrings.append('%s.py, line %d\n' % (stack.module, stack.lineno))
        stack = stack.tb_next
        limit -= 1
    return stackstrings

def trackstackstr(stack=None, limit=None):
    stackstrings = trackstacklist(stack, limit=limit)
    return ''.join(stackstrings)

def _get_traceback_list(err, tb=None, limit=None):
    name = getattr(getattr(err, '__class__', None), '__name__', 'Unknown exception')
    msg = ['%s: %s\n' % (name, err), 'Traceback:\n']
    try:
        msg.extend(trackstacklist(tb, limit=limit))
    except:
        pass
    return msg

def _get_traceback(err, tb=None, limit=None):
    return ''.join(_get_traceback_list(err, tb, limit=limit))

def exit(val=None):
    raise SystemExit(val)

class _StdStream(object):
    def __init__(self):
        self.content = ''

    def flush(self):
        content = self.content
        JS("$p['_print_to_console'](@{{content}})")
        self.content = ''

    def write(self, output):
        self.content += output
        if self.content.endswith('\n'):
            self.flush()

stdin  = None
stdout = None
stderr = None

def sys_init():
    global stdout
    stdout = _StdStream()

    global stderr
    stderr = _StdStream()

sys_init()
