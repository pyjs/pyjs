from __pyjamas__ import JS, debugger


SEARCH_ERROR = 0
PY_SOURCE = 1
PY_COMPILED = 2
C_EXTENSION = 3
PY_RESOURCE = 4
PKG_DIRECTORY = 5
C_BUILTIN = 6
PY_FROZEN = 7
PY_CODERESOURCE = 8
IMP_HOOK = 9

JS_SOURCE = 101
JS_COMPILED = 102


class NullImporter(object):
    def __init__(self, path_string):
        self.path_string = path_string

    def find_module(self, fullname, path=None):
        return None


def acquire_lock():
    """acquire_lock() -> None
Acquires the interpreter's import lock for the current thread.
This lock should be used by import hooks to ensure thread-safety
when importing modules.
On platforms without threads, this function does nothing."""
    # We don't have threads
    return None

def find_module(name, path=None):
    """find_module(name, [path]) -> (file, filename, (suffix, mode, type))
Search for a module.  If path is omitted or None, search for a
built-in, frozen or special module and continue search in sys.path.
The module name cannot contain '.'; to search for a submodule of a
package, pass the submodule name and the package's __path__."""
    if path is not None:
        name = '.'.join(path) + '.' + name
    if JS("""typeof $pyjs['loaded_modules'][@{{name}}['valueOf']()] != 'undefined'"""):
        return (None, name, ('', '', JS_COMPILED))
    # TODO: dynamic loading
    # if JS("$pyjs['options']['dynamic_loading']"):
    # return (jscode, name, ('js', '', JS_SOURCE))
    raise ImportError("No module named %s" % name)

def get_frozen_object(name):
    raise ImportError("No such frozen object named %s" % name)

def get_magic():
    """get_magic() -> string
Return the magic number for .pyc or .pyo files."""
    raise NotImplementedError

def get_suffixes():
    """get_suffixes() -> [(suffix, mode, type), ...]
Return a list of (suffix, mode, type) tuples describing the files
that find_module() looks for."""
    return [('.js', '', JS_SOURCE)]
    return [('.py', '', PY_SOURCE), ('.js', '', JS_SOURCE)]

def init_builtin():
    raise NotImplementedError

def init_frozen():
    raise NotImplementedError

def is_builtin():
    if name not in sys.builtin_modules:
        return 0
    if name in __builtins__.non_reloadable_module_names:
        return -1
    return 1

def is_frozen():
    # We don't support frozen modules
    return False

def load_compiled():
    raise NotImplementedError

def load_dynamic():
    raise NotImplementedError

def load_module(name, file, filename, info):
    """load_module(name, file, filename, (suffix, mode, type)) -> module
Load a module, given information returned by find_module().
The module name must include the full package name, if any."""
    suffix, mode, type = info
    if file is None:
        module = JS("""$pyjs['loaded_modules'][@{{filename}}['valueOf']()]""")
        sys.modules[name] = module
        #debugger()
        JS("""@{{module}}['$module_init'](@{{name}})""")
        return module
    # TODO: Handle other types (for dynamic load)
    raise NotImplementedError

def load_package():
    raise NotImplementedError

def load_source():
    raise NotImplementedError

def lock_held():
    """lock_held() -> boolean
Return True if the import lock is currently held, else False.
On platforms without threads, return False."""
    # We don't have threads
    return False

def new_module(name):
    """new_module(name) -> module
Create a new module.  Do not enter it in sys.modules.
The module name must include the full package name, if any."""
    # This is not used in pyjs
    return __builtins__.__class__(name)

def release_lock():
    """release_lock() -> None
Release the interpreter's import lock.
On platforms without threads, this function does nothing."""
    # We don't have threads
    pass

def reload(module):
    """reload(module) -> module
Reload the module.
The module must have been successfully imported before."""
    raise NotImplementedError

import dynamic
