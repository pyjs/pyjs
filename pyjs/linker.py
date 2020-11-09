import os
import sys
import pyjs.util as util
import logging
import pyjs
import subprocess
from pyjs import options
from pyjs import translator
if translator.name == 'proto':
    builtin_module = 'pyjslib'
elif translator.name == 'dict':
    builtin_module = '__builtin__'
else:
    raise ValueError("unknown translator engine '%s'" % translator.name)
translate_cmd = 'translator.py'
translate_cmd_opts = ['--use-translator=%s' % translator.name]


PYLIB_PATH = os.path.join(os.path.dirname(__file__), 'lib')
BUILTIN_PATH = os.path.join(os.path.dirname(__file__), 'builtin')
if pyjs.pyjspth is None:
    PYJAMASLIB_PATH = os.path.split(os.path.dirname(__file__))[0]
    PYJAMASLIB_PATH = os.path.split(PYJAMASLIB_PATH)[0]
    PYJAMASLIB_PATH = os.path.join(os.path.split(PYJAMASLIB_PATH)[0], 'library')
else:
    try:
        import pyjswidgets
        PYJAMASLIB_PATH = os.path.dirname(pyjswidgets.__file__)
    except ImportError:
        PYJAMASLIB_PATH = os.path.join(pyjs.pyjspth, "library")


translator_opts = options.all_compile_options.keys()
non_boolean_opts = ['translator']
assert set(non_boolean_opts) < set(translator_opts)

def is_modified(in_file,out_file):
    modified = False
    in_mtime = os.path.getmtime(in_file)
    try:
        out_mtime = os.path.getmtime(out_file)
        if in_mtime > out_mtime:
            modified = True
    except:
        modified = True
    return modified

def get_translator_opts(args):
    opts = []
    for k in options.mappings:
        if k in args:
            #XXX somewhat of a hack ... should have a method
            # for default positive and default negative
            nk = options.mappings[k]['names'][0]
            if k in non_boolean_opts:
                opts.append("%s=%s" % (nk, args[k]))
            elif args[k]:
                opts.append("%s" % nk)
            elif k != 'list_imports':
                opts.append(nk.replace('en', 'dis', 1))
    return opts

def parse_outfile(out_file):
    deps = []
    jslibs = []

    f = open(out_file)
    spos = os.path.getsize(out_file) - 200
    if spos < 0:
        spos = 0
    while True:
        f.seek(spos)
        txt = f.read(200)
        p = txt.find('/* end module:')
        if p >= 0:
            f.seek(spos + p)
            txt = f.read()
            break
        spos -= 100
        if spos < 0:
            raise ValueError("Invalid file: %s" % out_file)
    for l in txt.split("\n"):
        if l.startswith("PYJS_DEPS:"):
            deps = eval(l[10:])

    for l in txt.split("\n"):
        if l.startswith("PYJS_JS:"):
            jslibs = eval(l[8:])

    f.close()

    return deps, jslibs

def out_translate(platform, file_names, out_file, module_name,
                   translator_args, incremental):
    do_translate = False    # flag for incremental translate mode
    if translator_args.get('list_imports', None):
        do_translate = True
    # see if we can skip this module
    elif incremental:    # if we are in incremental translate mode
        # check for any files that need built
        for file_name in file_names:
            if is_modified(file_name,out_file):
                if platform is not None:
                    platform = "[%s] " % platform
                else:
                    platform = ''
                print("Translating file %s:" % platform, file_name)
                do_translate = True
                break
    if not incremental or do_translate:
        pydir = os.path.abspath(os.path.dirname(__file__))
        if not 'PYJS_SYSPATH' in os.environ:
            os.environ['PYJS_SYSPATH'] = sys.path[0]
        opts = ["--module-name", module_name, "-o"]
        if sys.platform == 'win32':
            opts.append(out_file)
            shell = False
        else:
            file_names = map(lambda x: x.replace(" ", r"\ "), file_names)
            opts.append(out_file.replace(" ", r"\ "))
            shell=True

        opts += get_translator_opts(translator_args) + file_names
        opts = [pyjs.PYTHON] + [os.path.join(pydir, translate_cmd)] + translate_cmd_opts + opts

        pyjscompile_cmd = '"%s"' % '" "'.join(opts)

        proc = subprocess.Popen(pyjscompile_cmd,
                           stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE,
                           shell=shell,
                           cwd=pydir,
                           env=os.environ
                           )
        stdout_value, ret = proc.communicate('')[0], proc.returncode
        if ret:
            raise translator.TranslationError('general fail in translator process')

    if translator_args.get('list_imports', None):
        print("List Imports %s:" % platform, file_names)
        print(stdout_value)
        return [], []

    deps, js_libs = parse_outfile(out_file)
    # use this to create dependencies for Makefiles.  maybe.
    #print "translate", out_file, deps, js_libs, stdout_value

    return deps, js_libs

_path_cache= {}
def module_path(name, path, platform=None):
    if name == '__pyjamas__' or name == '__javascript__':
        platform = None
    global _path_cache
    candidates = []
    packages = {}
    modules = {}
    if name.endswith('.js'):
        parts = [name]
    else:
        parts = name.split('.')
        if platform:
            parts[-1] = "%s.%s" % (parts[-1], platform)
            name = "%s/%s" % (name, platform)
    if not name in _path_cache:
        _path_cache[name] = {}
    for p in path:
        if p in _path_cache[name]:
            if _path_cache[name][p] is None:
                continue
            return _path_cache[name][p]
        if platform:
            cp = os.path.join(*([p] + parts))
            if name in _path_cache:
                cache = _path_cache[name]
            else:
                cache = {}
                _path_cache[name] = cache
            if os.path.exists(cp + '.py'):
                cache[p] = cp + '.py'
        else:
            tail = []
            for pn in parts:
                tail.append(pn)
                mn = '.'.join(tail)
                cp = os.path.join(*([p] + tail))
                if mn in _path_cache:
                    cache = _path_cache[mn]
                else:
                    cache = {}
                    _path_cache[mn] = cache
                if p in cache:
                    if cache[p] is None:
                        break
                elif os.path.isdir(cp) and os.path.exists(
                    os.path.join(cp, '__init__.py')):
                    cache[p] = os.path.join(cp, '__init__.py')
                elif os.path.exists(cp + '.py'):
                    cache[p] = cp + '.py'
                elif pn.endswith('.js') and os.path.exists(cp):
                    cache[p] = cp
                else:
                    cache[p] = None
        if p in _path_cache[name] and not _path_cache[name][p] is None:
            return _path_cache[name][p]
        _path_cache[name][p] = None

    return None
    raise RuntimeError( "Module %r not found" % name )


class BaseLinker(object):

    platform_parents = {}

    def __init__(self, modules, output='output',
                 compiler=None,
                 debug=False,
                 js_libs=[], static_js_libs=[], early_static_js_libs=[], late_static_js_libs=[], dynamic_js_libs=[],
                 early_static_app_libs = [], unlinked_modules = [], keep_lib_files = False,
                 platforms=[], path=[],
                 translator_arguments={},
                 compile_inplace=False,
                 list_imports=False,
                 translator_func=out_translate):
        modules = [mod.replace(os.sep, '.') for mod in modules]
        self.compiler = compiler
        self.js_path = os.path.abspath(output)
        self.top_module = modules[0]
        self.modules = modules
        self.output = os.path.abspath(output)
        self.js_libs = list(js_libs)
        self.static_js_libs = list(static_js_libs)
        self.early_static_js_libs = list(early_static_js_libs)
        self.late_static_js_libs = list(late_static_js_libs)
        self.dynamic_js_libs = list(dynamic_js_libs)
        self.early_static_app_libs = list(early_static_app_libs)
        self.unlinked_modules = unlinked_modules
        self.keep_lib_files = keep_lib_files
        self.platforms = platforms
        self.path = path + [PYLIB_PATH]
        self.translator_arguments = translator_arguments
        self.translator_func = translator_func
        self.compile_inplace = compile_inplace
        self.top_module_path = None
        self.remove_files = {}
        self.list_imports = list_imports

    def __call__(self):
        try:
            self.visited_modules = {}
            self.done = {}
            self.dependencies = {}
            self.visit_start()
            for platform in [None] + self.platforms:
                self.visit_start_platform(platform)
                old_path = self.path
                self.path = [BUILTIN_PATH, PYLIB_PATH, PYJAMASLIB_PATH]
                self.visit_modules([builtin_module], platform)
                self.path = old_path
                self.visit_modules(self.modules, platform)
                if not self.list_imports:
                    self.visit_end_platform(platform)
            if not self.list_imports:
                self.visit_end()
        except translator.TranslationError as e:
            raise

    def visit_modules(self, module_names, platform=None, parent_file = None):
        prefix = ''
        all_names = []
        for mn in module_names:
            if not mn.endswith(".js"):
                prefix = ''
                for part in mn.split('.')[:-1]:
                    pn = prefix + part
                    prefix = pn + '.'
                    if pn not in all_names:
                        all_names.append(pn)
            all_names.append(mn)
        #print "MODULES OF", parent_file, ":", module_names
        paths = self.path
        parent_base = None
        abs_name = None
        if not parent_file is None:
            for p in paths:
                if parent_file.find(p) == 0 and p != parent_file:
                    parent_base = p
                    abs_name = os.path.split(parent_file)[0]
                    abs_name = '.'.join(abs_name[len(parent_base)+1:].split(os.sep))

        for mn in all_names:
            p = None
            if abs_name:
                p = module_path(abs_name + '.' + mn, [parent_base])
                if p:
                    mn = abs_name + '.' + mn
            if not p:
                p = module_path(mn, paths)
            if not p:
                if "generic" in mn:
                    print("Module %r not found, sys.path is %r" % (mn, paths))
                continue
                #raise RuntimeError, "Module %r not found. Dep of %r" % (
                #    mn, self.dependencies)
            if mn==self.top_module:
                self.top_module_path = p
            override_paths=[]
            if platform:
                for pl in self.platform_parents.get(platform, []) + [platform]:
                    override_path = module_path(mn, paths, pl)
                    # prevent package overrides
                    if override_path and not override_path.endswith('__init__.py'):
                        override_paths.append(override_path)
            self.visit_module(p, override_paths, platform, module_name=mn)

    def visit_module(self, file_path, overrides, platform,
                     module_name):
        dir_name, file_name = os.path.split(file_path)
        if (     not file_name.endswith('.js')
             and file_name.split('.')[0] != module_name.split('.')[-1]
           ):
            if file_name == "__init__.py":
                if os.path.basename(dir_name) != module_name.split('.')[-1]:
                    return
            else:
                return
        self.merge_resources(dir_name)
        if platform and overrides:
            plat_suffix = '.__%s__' % platform
        else:
            plat_suffix = ''
        if self.compile_inplace:
            mod_part, extension = os.path.splitext(file_path)
            out_file = mod_part + plat_suffix + pyjs.MOD_SUFFIX
        else:
            out_file = os.path.join(self.output, 'lib',
                                    module_name + plat_suffix + pyjs.MOD_SUFFIX)
        if out_file in self.done.get(platform, []):
            return

        # translate if
        #  -    no platform
        #  - or if we have an override
        #  - or the module is used in an override only
        if (   platform is None
            or (platform and overrides)
            or (out_file not in self.done.get(None,[]))
           ):
            if file_name.endswith('.js'):
                if not self.list_imports:
                    fp = open(out_file, 'w')
                    fp.write("/* start javascript include: %s */\n" % file_name)
                    fp.write(open(file_path, 'r').read())
                    fp.write("$pyjs.loaded_modules['%s'] = " % file_name)
                    fp.write("function ( ) {return null;};\n")
                    fp.write("/* end %s */\n" % file_name)
                deps = []
                self.dependencies[out_file] = deps
            else:
                logging.info('Translating module:%s platform:%s out:%r' % (
                    module_name, platform or '-', out_file))
                deps, js_libs = self.translator_func(platform,
                                                     [file_path] +  overrides,
                                                     out_file,
                                                     module_name,
                                                     self.translator_arguments,
                                                     self.keep_lib_files)
                #deps, js_libs = translator.translate(self.compiler,
                #                            [file_path] +  overrides,
                #                            out_file,
                #                            module_name=module_name,
                #                            **self.translator_arguments)
                self.dependencies[out_file] = deps
                for path, mode, location in js_libs:
                    if mode == 'default':
                        if self.multi_file:
                            mode = 'dynamic'
                        else:
                            mode = 'static'
                    if mode == 'dynamic':
                        self.dynamic_js_libs.append(path)
                    elif mode == 'static':
                        if location == 'early':
                            self.early_static_js_libs.append(path)
                        elif location == 'middle':
                            self.static_js_libs.append(path)
                        elif location == 'late':
                            self.late_static_js_libs.append(path)
                        else:
                            raise RuntimeError( "Unknown js lib location: %r" % location )
                    else:
                        raise RuntimeError( "Unknown js lib mode: %r" % mode )

                if '.' in module_name:
                    for i, dep in enumerate(deps):
                        if module_path(dep, path=[dir_name]):
                            deps[i] = '.'.join(module_name.split('.')[:-1] + [dep])
        else:
            deps = self.dependencies[out_file]
        if out_file not in self.done.setdefault(platform, []):
            self.done[platform].append(out_file)
        if module_name not in self.visited_modules.setdefault(platform, []):
            self.visited_modules[platform].append(module_name)
        if deps:
            self.visit_modules(deps, platform, file_path)

    def merge_resources(self, dir_name):
        """gets a directory path for each module visited, this can be
        used to collect resources e.g. public folders"""
        pass

    def visit_start(self):
        if not os.path.exists(self.output):
            os.mkdir(self.output)
        if not self.compile_inplace:
            lib_dir = os.path.join(self.output, 'lib')
            if not os.path.exists(lib_dir):
                os.mkdir(lib_dir)

    def visit_start_platform(self, platform):
        pass

    def visit_end_platform(self, platform):
        pass

    def visit_end(self):
        pass


mappings = options.Mappings()
get_linker_options = mappings.link
add_linker_options = mappings.bind


mappings.multi_file = (
    ['--dynamic-link'],
    ['-m', '--multi-file'],
    [],
    dict(help='shared modules linked BEFORE runtime (late-bind) ASYNC <script>',
         default=False)
)
mappings.unlinked_modules = (
    ['--dynamic-load'],
    ['--dynamic'],
    [],
    dict(help='shared modules linked DURING runtime (on-demand), regex; SYNC XHR',
         type='string',
         action='append',
         metavar='REGEX',
         default=[])
)
mappings.js_includes = (
    ['--static-link'],
    ['-j', '--include-js'],
    [],
    dict(help='<script>s loaded in the application frame',
         type='string',
         action='append',
         metavar='FILE',
         default=[])
)
mappings.library_dirs = (
    ['-I', '--search-path'],
    ['--library_dir'],
    [],
    dict(help='additional paths appended to PYJSPATH',
         type='string',
         action='append',
         metavar='PATH',
         default=[])
)
mappings.output = (
    ['-o', '--output'],
    [],
    [],
    dict(help='assemble/finalize project in this directory',
         metavar='PATH',
         default='output')
)
